#!/usr/bin/env bash
# Reset Nanobot: stop all gateways, rebuild images, and restart them.
# Tailscale auth is already done at first-time setup; no auth key needed here.
# Run from the nanobot repo root, or call from upgrade.sh after a git pull.

set -e
cd "$(dirname "$0")"

echo "==> Stopping helper then main (with Tailscale) — helper first so shared network can be removed"
docker compose -f docker-compose.helper.yml -f docker-compose.helper.tailscale.yml down
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml down
docker compose -f docker-compose.research.yml -f docker-compose.research.tailscale.yml down

echo "==> Rebuilding images"
docker compose build
docker compose -f docker-compose.helper.yml build
docker compose -f docker-compose.research.yml build

echo "==> Starting main bot (Tailscale)"
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d
docker compose -f docker-compose.research.yml -f docker-compose.research.tailscale.yml up -d

echo "==> Starting helper bot (Tailscale)"
docker compose -f docker-compose.helper.yml -f docker-compose.helper.tailscale.yml up -d
docker compose -f docker-compose.research.yml -f docker-compose.research.tailscale.yml up -d

echo "==> Done. Main, helper, and research gateways are up on the Tailscale network (port 18790 on each node)."
