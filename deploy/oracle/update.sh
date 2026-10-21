#!/usr/bin/env bash
# Run by cron every 5 minutes: if GitHub's main branch has new commits, pull them and rebuild the app.
set -euo pipefail
cd "$(dirname "$0")/../.."
git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  git reset -q --hard origin/main
  sudo docker compose -f deploy/oracle/docker-compose.yml up -d --build
  sudo docker image prune -f > /dev/null
  echo "$(date -Is) deployed $(git rev-parse --short HEAD)"
fi
