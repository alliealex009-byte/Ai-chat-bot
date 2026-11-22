#!/usr/bin/env bash
# Local health check for cron/monitoring. Exit 0 = healthy, 1 = something is down.
# Cron example (every 5 min):  */5 * * * * /opt/ria/scripts/healthcheck.sh || logger -t ria "healthcheck failed"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="$(grep -E '^API_PORT=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2-)"; PORT="${PORT:-8000}"
fail=0
check() { if eval "$2" >/dev/null 2>&1; then echo "OK    $1"; else echo "DOWN  $1"; fail=1; fi; }

check "systemd ria.service"   "systemctl is-active --quiet ria"
check "Ollama API (local)"    "curl -fsS --max-time 4 http://127.0.0.1:11434/api/tags"
check "Model gemma3:4b"       "curl -fsS --max-time 4 http://127.0.0.1:11434/api/tags | grep -q gemma3:4b"
check "ria-mongo container"   "[ \"\$(docker inspect -f '{{.State.Health.Status}}' ria-mongo)\" = healthy ]"
check "RIA API /health"       "curl -fsS --max-time 6 http://127.0.0.1:$PORT/api/v1/health | grep -q '\"ok\"'"
exit $fail
