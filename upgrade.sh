#!/usr/bin/env bash
# Upgrade Nanobot: pull latest, rebuild images, restart main and helper gateways
# with Tailscale. Run from the nanobot repo root.
# Tailscale auth is already done at first-time setup; no auth key needed here.

set -e
cd "$(dirname "$0")"

echo "==> git pull"
git pull

echo "==> Stopping main and helper (with Tailscale)"
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml down
docker compose -f docker-compose.helper.yml -f docker-compose.helper.tailscale.yml down

echo "==> Rebuilding images"
docker compose build
docker compose -f docker-compose.helper.yml build

echo "==> Starting main bot (Tailscale)"
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d

echo "==> Starting helper bot (Tailscale)"
docker compose -f docker-compose.helper.yml -f docker-compose.helper.tailscale.yml up -d

echo "==> Done. Main and helper gateways are up on the Tailscale network (port 18790 on each node)."
