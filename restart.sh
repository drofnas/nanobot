#!/usr/bin/env bash
# Restart Nanobot: stop all gateways, rebuild images, and restart them.
# Tailscale auth is handled on first boot via TS_AUTHKEY; no key needed here.
# Run from the nanobot repo root, or call from upgrade.sh after a git pull.

set -e
cd "$(dirname "$0")"

echo "==> Stopping all bots"
docker compose down

echo "==> Rebuilding images"
docker compose build

echo "==> Starting all bots"
docker compose up -d

echo "==> Done. All bots are back up"
