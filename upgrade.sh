#!/usr/bin/env bash
# Upgrade Nanobot: pull latest, then reset (rebuild + restart) all gateways.
# Run from the nanobot repo root.

set -e
cd "$(dirname "$0")"

echo "==> git pull"
git pull

bash "$(dirname "$0")/reset.sh"
