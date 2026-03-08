import asyncio
import json
from datetime import datetime, time, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from nanobot.config.schema import HeartbeatSchedule, ScheduleWindow
from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMResponse, ToolCallRequest


class DummyProvider:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = DummyProvider([])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_trigger_now_executes_when_decision_is_run(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    called_with: list[str] = []

    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result == "done"
    assert called_with == ["check open tasks"]


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    async def _on_execute(tasks: str) -> str:
        return tasks

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    assert await service.trigger_now() is None


# ---------------------------------------------------------------------------
# Schedule window tests
# ---------------------------------------------------------------------------

def _make_service(schedule=None, interval_s=900, tmp_path=None):
    """Helper: build a HeartbeatService with minimal config."""
    from pathlib import Path
    provider = DummyProvider([])
    return HeartbeatService(
        workspace=tmp_path or Path("/tmp"),
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=interval_s,
        schedule=schedule,
    )


def _fake_now(hour: int, minute: int, tz_name: str = "UTC"):
    """Return a datetime fixed at the given hour:minute in the given timezone."""
    tz = ZoneInfo(tz_name)
    return datetime(2024, 1, 15, hour, minute, 0, tzinfo=tz)


def test_in_schedule_window_no_schedule(tmp_path):
    """No schedule configured → always allowed."""
    service = _make_service(schedule=None, tmp_path=tmp_path)
    assert service._in_schedule_window() is True


def test_in_schedule_window_empty_windows(tmp_path):
    """Schedule with empty windows list → always allowed."""
    schedule = HeartbeatSchedule(timezone="UTC", windows=[])
    service = _make_service(schedule=schedule, tmp_path=tmp_path)
    assert service._in_schedule_window() is True


def test_in_schedule_window_normal_inside(tmp_path):
    """Normal (same-day) window: 09:00–17:00; 12:00 should be inside."""
    schedule = HeartbeatSchedule(
        timezone="UTC",
        windows=[ScheduleWindow(start="09:00", end="17:00")],
    )
    service = _make_service(schedule=schedule, interval_s=900, tmp_path=tmp_path)
    with patch("nanobot.heartbeat.service.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(12, 0)
        assert service._in_schedule_window() is True


def test_in_schedule_window_normal_outside(tmp_path):
    """Normal window 09:00–17:00; 20:00 should be outside."""
    schedule = HeartbeatSchedule(
        timezone="UTC",
        windows=[ScheduleWindow(start="09:00", end="17:00")],
    )
    service = _make_service(schedule=schedule, interval_s=900, tmp_path=tmp_path)
    with patch("nanobot.heartbeat.service.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(20, 0)
        assert service._in_schedule_window() is False


def test_in_schedule_window_overnight_inside(tmp_path):
    """Overnight window 23:00–06:00; 02:00 should be inside."""
    schedule = HeartbeatSchedule(
        timezone="UTC",
        windows=[ScheduleWindow(start="23:00", end="06:00")],
    )
    # interval_s=900 → effective end = 05:45; 02:00 is well inside
    service = _make_service(schedule=schedule, interval_s=900, tmp_path=tmp_path)
    with patch("nanobot.heartbeat.service.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(2, 0)
        assert service._in_schedule_window() is True


def test_in_schedule_window_overnight_outside(tmp_path):
    """Overnight window 23:00–06:00; 10:00 should be outside."""
    schedule = HeartbeatSchedule(
        timezone="UTC",
        windows=[ScheduleWindow(start="23:00", end="06:00")],
    )
    service = _make_service(schedule=schedule, interval_s=900, tmp_path=tmp_path)
    with patch("nanobot.heartbeat.service.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(10, 0)
        assert service._in_schedule_window() is False


def test_in_schedule_window_interval_boundary_just_inside(tmp_path):
    """Overnight 23:00–06:00 with 15-min interval: 05:45 is the last valid tick."""
    schedule = HeartbeatSchedule(
        timezone="UTC",
        windows=[ScheduleWindow(start="23:00", end="06:00")],
    )
    service = _make_service(schedule=schedule, interval_s=900, tmp_path=tmp_path)
    with patch("nanobot.heartbeat.service.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(5, 45)
        assert service._in_schedule_window() is True


def test_in_schedule_window_interval_boundary_just_outside(tmp_path):
    """Overnight 23:00–06:00 with 15-min interval: 05:46 is too late."""
    schedule = HeartbeatSchedule(
        timezone="UTC",
        windows=[ScheduleWindow(start="23:00", end="06:00")],
    )
    service = _make_service(schedule=schedule, interval_s=900, tmp_path=tmp_path)
    with patch("nanobot.heartbeat.service.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(5, 46)
        assert service._in_schedule_window() is False


def test_reload_config_updates_fields(tmp_path):
    """_reload_config() should update interval_s, enabled, and schedule from disk."""
    config_data = {
        "gateway": {
            "heartbeat": {
                "enabled": False,
                "intervalS": 300,
                "schedule": {
                    "timezone": "America/Los_Angeles",
                    "windows": [{"start": "23:00", "end": "06:00"}],
                },
            }
        }
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    service = _make_service(schedule=None, interval_s=900, tmp_path=tmp_path)
    service._config_path = config_file

    service._reload_config()

    assert service.enabled is False
    assert service.interval_s == 300
    assert service.schedule is not None
    assert service.schedule.timezone == "America/Los_Angeles"
    assert len(service.schedule.windows) == 1
    assert service.schedule.windows[0].start == "23:00"
