#!/usr/bin/env bash
# Reset Nanobot: stop all gateways, rebuild images, and restart them.
# Tailscale auth is already done at first-time setup; no auth key needed here.
# Run from the nanobot repo root, or call from upgrade.sh after a git pull.

set -e
cd "$(dirname "$0")"

echo "==> Stopping all bots (with Tailscale)"
docker compose -f docker-compose.helper.yml -f docker-compose.helper.tailscale.yml down
docker compose -f docker-compose.research.yml -f docker-compose.research.tailscale.yml down
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml down

echo "==> Rebuilding images"
docker compose build
docker compose -f docker-compose.helper.yml build
docker compose -f docker-compose.research.yml build

echo "==> Starting main bot (Tailscale)"
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d --remove-orphans

echo "==> Starting extra bots (Tailscale)"
docker compose -f docker-compose.helper.yml -f docker-compose.helper.tailscale.yml up -d --remove-orphans
docker compose -f docker-compose.research.yml -f docker-compose.research.tailscale.yml up -d --remove-orphans

echo "==> Done. Bots are all back up (Tailscale network)"
