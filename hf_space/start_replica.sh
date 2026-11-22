#!/usr/bin/env bash
# Starts Ollama (localhost only), pulls the model in the background, then the web app on :7860.
# Model storage is in /tmp (ephemeral): it is re-downloaded on every Space restart.
set -u
ollama serve >/tmp/ollama.log 2>&1 &
( for _ in $(seq 1 30); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 2; done
  ollama pull "${OLLAMA_MODEL:-gemma3:4b}" >>/tmp/ollama.log 2>&1 ) &
exec uvicorn app:app --host 0.0.0.0 --port 7860 --proxy-headers --forwarded-allow-ips "*"
