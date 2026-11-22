#!/usr/bin/env bash
# Update RIA from GitHub. Preserves .env, data volume and logs.  Run: bash scripts/update.sh  (needs sudo for systemctl)
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Updating dependencies"
./venv/bin/pip install --quiet -r requirements.txt

echo "==> Ensuring RIA's MongoDB container is up (data volume is kept)"
docker compose -p ria --env-file .env -f deploy/docker-compose.yml up -d

if [ -f /etc/systemd/system/ria.service ] && ! diff -q <(sed "s|/opt/ria|$APP_DIR|g" deploy/ria.service) /etc/systemd/system/ria.service >/dev/null; then
  echo "==> systemd unit changed; updating"
  sed "s|/opt/ria|$APP_DIR|g" deploy/ria.service | sudo tee /etc/systemd/system/ria.service >/dev/null
  sudo systemctl daemon-reload
fi

echo "==> Restarting RIA"
sudo systemctl restart ria
sleep 4
sudo systemctl status ria --no-pager || true
echo "==> Health"
bash scripts/healthcheck.sh || true
