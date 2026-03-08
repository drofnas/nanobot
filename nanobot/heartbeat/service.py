"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine
from zoneinfo import ZoneInfo

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import HeartbeatSchedule
    from nanobot.providers.base import LLMProvider

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.  This avoids free-text parsing
    and the unreliable HEARTBEAT_OK token.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop and
    returns the result to deliver.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
        schedule: HeartbeatSchedule | None = None,
        config_path: Path | None = None,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self.schedule = schedule
        self._config_path = config_path
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def _reload_config(self) -> None:
        """Re-read heartbeat config from disk so changes are picked up without a restart."""
        if not self._config_path:
            return
        try:
            from nanobot.config.loader import load_config
            cfg = load_config(self._config_path).gateway.heartbeat
            self.enabled = cfg.enabled
            self.interval_s = cfg.interval_s
            self.schedule = cfg.schedule
        except Exception as e:
            logger.warning("Failed to reload heartbeat config: {}", e)

    def _in_schedule_window(self) -> bool:
        """Return True if the current time falls within an active schedule window.

        When no schedule is configured (or windows list is empty) the heartbeat
        is always allowed to run.  The effective end of each window is pulled
        back by ``interval_s`` so that a tick is only allowed to start when a
        full interval still fits before the window closes.
        """
        if not self.schedule or not self.schedule.windows:
            return True

        tz = ZoneInfo(self.schedule.timezone)
        now = datetime.now(tz).time().replace(second=0, microsecond=0)

        for w in self.schedule.windows:
            start = time.fromisoformat(w.start)
            end = time.fromisoformat(w.end)

            # Pull the effective end back by interval_s (in whole minutes).
            end_mins = end.hour * 60 + end.minute
            eff_end_mins = end_mins - self.interval_s // 60
            # Clamp to [0, 1439] and wrap correctly within a 24-hour clock.
            eff_end_mins = eff_end_mins % (24 * 60)
            eff_end = time(eff_end_mins // 60, eff_end_mins % 60)

            # Overnight window: start > eff_end (e.g. 23:00 – 05:45)
            if start > eff_end:
                in_window = now >= start or now <= eff_end
            else:
                in_window = start <= now <= eff_end

            if in_window:
                return True

        return False

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                self._reload_config()
                if not self.enabled:
                    logger.info("Heartbeat disabled via config; stopping")
                    self._running = False
                    break
                await asyncio.sleep(self.interval_s)
                if self._running and self._in_schedule_window():
                    await self._tick()
                elif self._running:
                    logger.debug("Heartbeat: outside schedule window, skipping tick")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)
                if response and self.on_notify:
                    logger.info("Heartbeat: completed, delivering response")
                    await self.on_notify(response)
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
