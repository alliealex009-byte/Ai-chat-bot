#!/usr/bin/env bash
# RIA installer for Ubuntu 22.04. Run from the repo root (e.g. /opt/ria):  sudo bash scripts/install.sh
# Safe to re-run: never overwrites .env, never deletes data, never touches other containers/services.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="ria"
MODEL="${OLLAMA_MODEL:-gemma3:4b}"
OLLAMA_URL="http://127.0.0.1:11434"

ok()   { printf '\033[32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run with sudo:  sudo bash scripts/install.sh"
cd "$APP_DIR"
echo "Installing RIA from $APP_DIR"

# 1. OS + Python ---------------------------------------------------------
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || warn "Not Ubuntu (${PRETTY_NAME:-unknown}); this script targets Ubuntu 22.04"
ok "OS: ${PRETTY_NAME:-unknown}"
command -v python3 >/dev/null || die "python3 not found"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || die "Python 3.10+ required"
ok "Python: $(python3 --version)"
python3 -c 'import venv, ensurepip' 2>/dev/null || die "Missing venv: sudo apt install -y python3-venv"

# 2. Ollama + model ------------------------------------------------------
command -v curl >/dev/null || die "curl not found (sudo apt install -y curl)"
TAGS="$(curl -fsS --max-time 5 "$OLLAMA_URL/api/tags")" || die "Ollama not reachable at $OLLAMA_URL (systemctl status ollama)"
ok "Ollama reachable"
echo "$TAGS" | grep -q "\"name\":\"$MODEL\"" || die "Model $MODEL not installed. Run: ollama pull $MODEL"
ok "Model $MODEL present (qwen3:4b / qwen2.5:3b are NOT used)"
if ss -tln 2>/dev/null | grep -E ':11434\s' | grep -qvE '127\.0\.0\.1|\[::1\]'; then
  warn "Ollama seems to listen on a public interface! Set OLLAMA_HOST=127.0.0.1 and block 11434 in the firewall."
fi

# 3. Docker ---------------------------------------------------------------
command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not found"
ok "Docker OK"

# 4. Service user + dirs -------------------------------------------------
id "$SERVICE_USER" >/dev/null 2>&1 || { useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"; ok "Created user $SERVICE_USER"; }
mkdir -p logs data backups
ok "Directories ready"

# 5. .env (preserved if it exists) ----------------------------------------
if [ -f .env ]; then
  ok ".env already exists - keeping it untouched"
else
  cp .env.example .env
  chmod 600 .env
  MP="$(openssl rand -hex 24)"; AT="$(openssl rand -hex 32)"
  sed -i "s|^MONGO_PASSWORD=.*|MONGO_PASSWORD=${MP}|" .env
  sed -i "s|^API_TOKEN=.*|API_TOKEN=${AT}|" .env
  ok "Created .env with generated MONGO_PASSWORD and API_TOKEN"
  warn "Edit .env and set TELEGRAM_BOT_TOKEN (and ADMIN_USER_IDS):  nano $APP_DIR/.env"
fi
chmod 600 .env

# 6. MongoDB (own container, localhost:27018) ------------------------------
if docker ps --format '{{.Names}}' | grep -qx ria-mongo; then
  ok "ria-mongo already running"
else
  if ss -tln | grep -qE '127\.0\.0\.1:27018\s'; then
    die "Port 27018 is already in use by something that is not ria-mongo. Free it or change the port in deploy/docker-compose.yml and .env."
  fi
  docker compose -p ria --env-file .env -f deploy/docker-compose.yml up -d
  ok "Started ria-mongo"
fi
echo -n "Waiting for MongoDB health"
for _ in $(seq 1 40); do
  st="$(docker inspect -f '{{.State.Health.Status}}' ria-mongo 2>/dev/null || echo none)"
  [ "$st" = "healthy" ] && break
  echo -n "."; sleep 3
done
echo
[ "$(docker inspect -f '{{.State.Health.Status}}' ria-mongo 2>/dev/null)" = "healthy" ] || die "ria-mongo not healthy. See: docker logs ria-mongo"
ok "MongoDB healthy"

# 7. Python venv + deps ---------------------------------------------------
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
ok "Dependencies installed"

chown -R "$SERVICE_USER:$SERVICE_USER" logs data
chown root:"$SERVICE_USER" .env && chmod 640 .env

# 8. systemd ---------------------------------------------------------------
sed "s|/opt/ria|$APP_DIR|g" deploy/ria.service > /etc/systemd/system/ria.service
systemctl daemon-reload
systemctl enable ria >/dev/null 2>&1
ok "systemd unit installed (ria.service)"

if grep -qE '^TELEGRAM_BOT_TOKEN=.+' .env; then
  systemctl restart ria
  sleep 4
  systemctl is-active --quiet ria && ok "RIA is running" || warn "RIA failed to start: journalctl -u ria -n 50 --no-pager"
else
  warn "TELEGRAM_BOT_TOKEN is empty. After editing .env run:  sudo systemctl restart ria"
fi

echo
echo "Next: HTTPS for the API (see README step 7), then deploy the Hugging Face Space."
echo "Your API_TOKEN (for the HF Space secret RIA_API_TOKEN):  grep ^API_TOKEN= $APP_DIR/.env"
