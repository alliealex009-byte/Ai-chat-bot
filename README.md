# RIA — Telegram AI Companion (Gemma 3 4B, Hinglish)

RIA is a fictional 21-year-old Indian Gen-Z AI companion that chats in natural Roman Hinglish.
She runs on **your Ubuntu VPS** with **Ollama + `gemma3:4b`**, remembers things you tell her (MongoDB),
and also has a **web chat + admin dashboard on a Hugging Face Space**.

```
Telegram ──► VPS: RIA process (ONE polling process) ──► Ollama gemma3:4b   (127.0.0.1:11434, never public)
                       │  FastAPI :8000 (127.0.0.1) ◄── HTTPS reverse proxy ◄── Hugging Face Space (web chat/admin)
                       └──► MongoDB "ria_database" (Docker, 127.0.0.1:27018, never public)
```

* **The VPS is the only thing that must stay up.** If the Space sleeps or dies, Telegram keeps working.
* Telegram and web chat share **one** history and **one** memory per user (the VPS MongoDB is the single source of truth).
* The Space stores **no user data**. It only talks to the VPS over an authenticated HTTPS API.
* Local Gemma is always primary. Optional extras (both **off by default**): Hugging Face inference replica, OpenRouter fallback.
  Providers are tried in a fixed order and only after the previous one fails; the provider used is logged and shown in the admin dashboard.
  RIA never switches to `qwen3:4b` / `qwen2.5:3b`.

> **Honest status.** The code was written and reviewed carefully, and the parts that don't need external services
> (config, persona/prompt rules, rate limiting, queue, memory logic, user isolation, forget, redaction, message splitting) pass automated tests.
> Tests that need the real libraries (Ollama HTTP client, Telegram handlers, FastAPI API, HF Space) are included but could only run
> once `pip install -r requirements-dev.txt` is available — **run `pytest` on your VPS before going live** (step 5), and the
> live Gemma test (`RIA_LIVE_TEST=1`) to hear RIA actually talk. Nothing here was tested against your real server yet.

---

## 1. What's in the repo

```
app/            VPS code: main.py, config.py, bot.py, personality.py, context.py
  ai/           ollama.py (primary), router.py, replica.py (optional HF), fallback.py (optional OpenRouter), prompts.py
  tg/           Telegram handlers (start, commands, chat, media)
  api/          FastAPI server for the HF Space
  database/     MongoDB repos (users, conversations, memories, web sessions)
  services/     chat_engine (shared by Telegram+web), queue, limiter, memory, maintenance
hf_space/       Hugging Face Docker Space (web chat, admin dashboard, optional replica)
deploy/         ria.service, docker-compose.yml (Mongo), nginx.conf, Caddyfile.snippet
scripts/        install.sh, update.sh, backup.sh, healthcheck.sh
tests/          pytest suite (+ live Gemma test)
.github/workflows/  ci.yml, deploy-hf.yml
```

(The Telegram handlers live in `app/tg/` instead of `app/telegram/` so the folder name can never shadow the `telegram` library.)

---

## 2. The two `.env` files

### A. VPS — `/opt/ria/.env` (copy of `.env.example`)

| Variable | What to put | Where it comes from |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token | @BotFather. **Use one token, one polling process.** |
| `ADMIN_USER_IDS` | your numeric Telegram id | @userinfobot. Enables `/health` only (admins do NOT get the owner panel; use `OWNER_USER_IDS`) |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://127.0.0.1:11434` / `gemma3:4b` | already the defaults |
| `MONGO_PASSWORD` | long random password | `install.sh` generates it |
| `MONGO_PORT` / `MONGO_DB_NAME` | `27018` / `ria_database` | defaults |
| `API_TOKEN` | ≥32 chars | `install.sh` generates it. **Same value → HF secret `RIA_API_TOKEN`** |
| `ENABLE_API_FALLBACK`, `OPENROUTER_*` | leave `false` / empty | only if you want a paid fallback |
| `HF_REPLICA_*` | leave `false` / empty | only if you enable the optional replica |
| `MAX_CONCURRENT_INFERENCE` | `2` | see tuning (§11) |

Never commit `.env` (it's in `.gitignore`). `chmod 600 .env`.

### B. Hugging Face Space — *Settings → Variables and secrets*

| Name | Type | Value |
|---|---|---|
| `RIA_API_URL` | Variable | `https://ria-api.yourdomain.com` (your VPS API, HTTPS) |
| `RIA_API_TOKEN` | **Secret** | same as VPS `API_TOKEN` |
| `ADMIN_PASSWORD` | **Secret** | long password for `/admin` (`openssl rand -base64 24`) |
| `SESSION_SECRET` | **Secret** | `openssl rand -hex 32` (signs admin cookies) |
| `ENABLE_REPLICA` | Variable | `false` (default) |
| `REPLICA_TOKEN` | **Secret** | only if replica enabled; same as VPS `HF_REPLICA_TOKEN` |

A template is in `hf_space/.env.example`. **Never** put these values in GitHub or in JavaScript.

---

## 3. Put the code on GitHub (from your phone)

1. GitHub mobile → **+ → New repository** → name `ria`, **Private**, create.
2. Upload the project files (easiest: on a computer/Termux `git push`; from the GitHub mobile app you can add files one by one via the web UI "Add file → Upload files").
   Keep the folder structure exactly as above. **Do not upload `.env`.**
3. Repo → *Settings → Secrets and variables → Actions*:
   * Secret `HF_TOKEN` — Hugging Face token with write access (create at huggingface.co/settings/tokens; fine-grained, limited to the `ria-ai-companion` Space).
   * Variable `HF_USERNAME` — your Hugging Face username.
   (No VPS credentials are ever stored in GitHub.)

---

## 4. VPS deployment (Termius) — one block at a time

Your existing `telegram-ai-sticker-bot`, `sticker-bot-mongo`, `tg-game-caddy-1`, `tg-game-game-1` are **not touched**:
RIA uses its own folder `/opt/ria`, its own Mongo container `ria-mongo` (port `127.0.0.1:27018`), its own Docker network/volume, and its own `ria.service`.

**4.1 Look at what's already running (read-only)**
```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo ss -tlnp | grep -E ':(80|443|8000|27018|11434)\s'
ollama list
```
You should see `gemma3:4b`. Nothing should already use 27018 or 8000.

**4.2 Clone**
```bash
sudo mkdir -p /opt/ria && sudo chown $USER:$USER /opt/ria
git clone https://github.com/YOUR_USER/ria.git /opt/ria
cd /opt/ria
```

**4.3 Install** (checks Ubuntu/Python/Ollama/model/Docker, starts `ria-mongo`, creates venv, installs systemd unit, creates `.env` with generated secrets)
```bash
sudo bash scripts/install.sh
```

**4.4 Add your Telegram token**
```bash
nano /opt/ria/.env          # set TELEGRAM_BOT_TOKEN= and ADMIN_USER_IDS=
sudo systemctl restart ria
sudo systemctl status ria --no-pager
journalctl -u ria -n 40 --no-pager
```

**4.5 Run the tests (before trusting it)**
```bash
cd /opt/ria && source venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
RIA_LIVE_TEST=1 pytest -q tests/test_live_ai.py -s     # real gemma3:4b replies — read them!
deactivate
```

**4.6 Talk to her** — open your bot in Telegram: `/start`, then `Hi`, `Mood off hai`, `Miss you`, `Tum AI ho kya?`.

**4.7 HTTPS for the API** (needed by the Space)
First check who owns ports 80/443:
```bash
sudo ss -tlnp | grep -E ':(80|443)\s'
```
* **Ports free →** use `deploy/nginx.conf` (instructions at the top of the file; certbot gives HTTPS).
* **`tg-game-caddy-1` owns 80/443 (likely) →** use `deploy/Caddyfile.snippet`: add one site block to that Caddy config
  (back the file up first). Caddy runs in Docker, so read the notes in the snippet about reaching `127.0.0.1:8000`.
  If unsure, ask before editing — a wrong Caddy edit would affect your game bot.

You need a DNS **A record** (e.g. `ria-api.yourdomain.com → your VPS IP`). Test:
```bash
curl -s https://ria-api.yourdomain.com/api/v1/health          # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://ria-api.yourdomain.com/api/v1/status   # 401 (needs token)
```

**4.8 Daily backups + health check (cron)**
```bash
sudo crontab -e   # add:
30 3 * * * /opt/ria/scripts/backup.sh >> /opt/ria/logs/backup.log 2>&1
*/5 * * * * /opt/ria/scripts/healthcheck.sh || logger -t ria "healthcheck failed"
```

### Updating later (your workflow)
```bash
cd /opt/ria
git pull --ff-only
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart ria
sudo systemctl status ria --no-pager
```
or simply `bash scripts/update.sh` (does the same and keeps `.env`, database and logs).

---

## 5. Hugging Face Space deployment

1. huggingface.co → **New Space** → name **`ria-ai-companion`** → SDK **Docker** → **CPU Basic** → Private or Public (private recommended). Your existing Group Manager Space is not touched.
2. Space → *Settings → Variables and secrets* → add the values from §2-B.
3. Deploy: either push to GitHub (workflow `deploy-hf.yml` copies `hf_space/` to the Space automatically), or manually:
   ```bash
   git clone https://huggingface.co/spaces/YOUR_HF_USER/ria-ai-companion
   cp -r /opt/ria/hf_space/. ria-ai-companion/ && cd ria-ai-companion
   git add -A && git commit -m "deploy" && git push
   ```
4. Open the Space's **direct URL** (`https://YOUR_HF_USER-ria-ai-companion.hf.space`), not the embedded view, so login cookies work.
5. **Web login:** in Telegram send `/link` to RIA → she replies with an 8-character one-time code (valid 10 min) → enter it on the web page.
   The web chat now shows the same history and memories as Telegram. `/admin` is the dashboard (password = `ADMIN_PASSWORD`).

**Hardware.** CPU Basic is free but limited, and free Spaces go to sleep when idle — **do not rely on it for 24/7**. That's fine here:
the Space is only a front end; the bot lives on the VPS. If the web UI feels slow or you want it always awake, upgrade hardware/“sleep time” in Space settings;
check current options and prices at huggingface.co/pricing (I haven't quoted numbers because they change). Running the optional Gemma **replica**
on a Space needs far more RAM/CPU than CPU Basic comfortably gives — only enable it if you accept slow answers or pay for bigger hardware.
The app is stateless, so you do **not** need persistent storage. If you ever want logs/files to survive restarts, attach a Hugging Face Storage Bucket/volume
from the Space settings (see HF docs) and write only non-sensitive data there — never user conversations.

### Optional replica (default OFF)
Rename `hf_space/Dockerfile.replica` → `Dockerfile` in the Space repo, set `ENABLE_REPLICA=true` + secret `REPLICA_TOKEN`, then on the VPS set
`HF_REPLICA_ENABLED=true`, `HF_REPLICA_URL=https://…hf.space`, `HF_REPLICA_TOKEN=…` and restart. VPS tries it only after local Ollama fails and only while its health check passes.

---

## 6. Telegram commands

`/start` `/help` `/reset` (clear chat, keep memories) `/memory` (list; `/memory delete 2`, `/memory edit 2 text`, `/memory add text`)
`/forget` (asks to confirm, then deletes history + memories + profile + web sessions) `/language` `/settings` `/name <naam>` `/link` `/about`
and `/health` (admin only). RIA works in private chats only. Stickers, photos and voice get a natural “can't do that yet” reply
(image understanding / speech-to-text are intentionally not in this release; add them as new handlers in `app/tg/media.py`).

## 7. The API (VPS, behind HTTPS)

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /api/v1/health` | none | only `{"status": "ok"/"degraded"}` |
| `GET /api/v1/status` `/model` `/stats` | service token | admin info (no conversation content) |
| `POST /api/v1/chat` | service token + user session | `{"message": "..."}` |
| `POST /api/v1/auth/redeem` | service token | link code → session token |
| `GET /api/v1/history`, `GET/DELETE /api/v1/memory…`, `POST /api/v1/reset`, `DELETE /api/v1/me` | token + session | always scoped to the session's user |
| `POST /api/v1/playground` | service token | stateless test inference (admin) |

Per-user and global rate limits, constant-time token compare, failed-auth throttling, no docs/openapi exposure, generic error messages.

---

## 8. Testing checklist (your 10 scenarios)

1. **Telegram via Gemma:** talk to the bot; `journalctl -u ria -f` shows `inference provider=ollama model=gemma3:4b latency_ms=…`.
2. **HF web chat via VPS API:** `/link` → code → web chat reply (admin dashboard shows `served by: ollama`).
3. **Mongo stores history:** `docker exec -it ria-mongo sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin ria_database --eval "db.messages.countDocuments()"'`
4. **Shared memory:** tell RIA on Telegram “mujhe cricket pasand hai” (after ~8 messages memory extraction runs; or `/memory add Likes cricket`), then ask on web.
5. **HF down:** pause the Space → Telegram still replies; `/health` still OK.
6. **Ollama restarts:** `sudo systemctl restart ollama` → during the restart RIA says a safe “dimag hang” message; the next message after Ollama is back works (no RIA restart needed).
7. **Mongo restarts:** `docker restart ria-mongo` → short “memory so raha hai” message, then recovery on its own.
8. **Isolation:** automated (`tests/test_chat_engine.py`, `tests/test_api.py`); manually: two Telegram accounts / two web sessions never see each other's history or memories.
9. **One poller:** `ps aux | grep "app.main" | grep -v grep` shows one process; a second `python -m app.main` exits with “Another RIA instance…”. Also Telegram `Conflict` is logged loudly if another machine polls the same token.
10. **Personality:** use `/admin → AI playground` and the live test to check short Hinglish replies, honesty about being an AI, no “beta/sir”.

---

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| `Configuration error: …` on start | `journalctl -u ria -n 30`; fix `.env` (token empty, `API_TOKEN` < 32 chars…) |
| Bot silent | `systemctl status ria`; `bash scripts/healthcheck.sh`; token correct? |
| `Telegram Conflict` in logs | another process/PC uses the same bot token — stop it |
| “model not found” | `ollama pull gemma3:4b` (RIA will not use another model) |
| Slow replies (10–40 s) | normal on CPU for first load; keep `OLLAMA_KEEP_ALIVE=30m`; see §11 |
| `Could not connect to MongoDB` | `docker ps` shows `ria-mongo` healthy? `docker logs ria-mongo`; password in `.env` must match the volume's original password |
| Changed `MONGO_PASSWORD` and Mongo rejects it | Mongo only reads it on first volume creation. Restore the old password, or (data loss!) `docker compose -p ria … down -v` |
| API 401 from Space | `RIA_API_TOKEN` ≠ VPS `API_TOKEN` |
| Space shows “RIA abhi available nahi” | `curl https://ria-api…/api/v1/health` from your phone; proxy/DNS/cert issue; Caddy cannot reach `127.0.0.1:8000` from Docker (see snippet) |
| Web login says code invalid | codes last 10 min, single use; send `/link` again |
| Web login loops | open the `*.hf.space` URL directly (embedded iframe blocks cookies) |
| `port 27018 in use` | change the port in `deploy/docker-compose.yml` and `.env` |

Logs: `journalctl -u ria -f` and `/opt/ria/logs/ria.log` (secrets are redacted; message text is not logged unless `LOG_MESSAGE_CONTENT=true`).

---

## 10. Security checklist

- [ ] `.env` is `chmod 640/600`, not in Git; Space values only in Space Secrets
- [ ] `ss -tlnp` shows Ollama on `127.0.0.1:11434` only, Mongo on `127.0.0.1:27018` only, API on `127.0.0.1:8000` only; the only public port is 443 (proxy)
- [ ] `ufw` allows 22/80/443 only (don't enable ufw blindly if other bots depend on other ports — check first)
- [ ] `API_TOKEN` ≥ 32 random chars; rotate by changing VPS `.env` + Space secret, restart both
- [ ] Reverse proxy forwards **only** `/api/v1/*`
- [ ] Mongo auth enabled, backups running (`scripts/backup.sh`), a restore tested at least once
- [ ] `LOG_MESSAGE_CONTENT=false`
- [ ] Telegram token never pasted in chats/logs (rotate with @BotFather if leaked)
- [ ] RIA has no command execution, no file access, no web browsing; user text is treated as chat, never as instructions; prompt-injection attempts are detected, counted and ignored by the persona rules
- [ ] Optional paid fallback keeps daily request/token limits

Prompt-injection protection is defence-in-depth (input sanitising, persona rules, no tools to abuse), not a guarantee against a 4B model being talked into odd replies.

---

## 11. Performance tuning (8 vCPU / 16 GB, CPU only)

* **Start with `MAX_CONCURRENT_INFERENCE=2`**, `AI_NUM_THREADS=8`. Gemma 3 4B uses ~4–5 GB RAM; more parallel jobs split the same CPU, so each reply gets slower — they don't add capacity. Try `1` if p95 latency (admin dashboard) is high.
* Keep Ollama's own parallelism modest: in `systemctl edit ollama` set `Environment="OLLAMA_NUM_PARALLEL=2"` and `Environment="OLLAMA_KEEP_ALIVE=30m"` (and `OLLAMA_HOST=127.0.0.1`).
* `AI_MAX_TOKENS=100` keeps chat replies short and fast; `AI_MAX_TOKENS_LONG` is used only for explanations.
* Smaller prompts = faster: lower `HISTORY_MESSAGES` (12 → 8) or `MEMORIES_IN_PROMPT` if replies are slow.
* The queue is bounded (`MAX_QUEUE_SIZE`) and each user gets one in-flight message: under load RIA answers “thodi bheed hai” rather than overloading the CPU. Capacity is **not unlimited**; expect roughly a few replies per minute per concurrent slot on CPU.
* Your sticker bot and game share this CPU/RAM: `MemoryMax` on `ria.service` and Mongo's 2 GB limit protect them; check `htop` during load.
* Memory extraction uses the same queue and local Gemma only (memory text never goes to a paid API).

## 12. Tuning RIA's personality

Everything about her voice is in `app/personality.py` (`PERSONA`): language ratio, length, examples, honesty and safety rules.
To iterate: edit the text → `sudo systemctl restart ria` → test in `/admin` playground (leave the system prompt empty to use the real persona, or paste a draft prompt to A/B test without restarting).
Gemma 3 4B follows short, concrete examples best — add 3–5 more example exchanges in your preferred style rather than long rules.
RIA is a *fictional AI persona*: she's told never to claim a body, real-life experiences or human feelings, and to admit she's an AI when asked.

## 13. v2 — Ria's personality, groups, stickers, owner panel

**Personality.** Ria is a 19-year-old Delhi college girl: very short Gen-Z Hinglish (3–12 words), feminine grammar, 0–2 fitting emojis,
light flirty/teasing within limits (no abuse, no sexual talk — she deflects playfully, e.g. "hehe itni jaldi? pehle dost toh ban jao 😏"),
no flirting if someone says they're under 18. She never brings up AI/bot/tech on her own: every reply is filtered (stage directions like "(giggles)" removed,
masculine verbs fixed, replies trimmed, "AI/digital/virtual" talk retried once then stripped). Tech questions ("kaun sa API?") get a playful "mujhe tech samajh nahi aata".
**One deliberate exception:** if someone *sincerely asks* "tum AI ho / real ho?", she answers truthfully in one short line in her voice and carries on —
she is never made to claim she is a human. (Everything else stays in character.)

**Groups.** In a group Ria answers only when someone says "Ria", @tags her, or replies to her message, and she replies *as a reply* to that message.
Group chats keep their own shared conversation (no personal memories are used in groups). **BotFather → /mybots → your bot → Bot Settings → Group Privacy → Turn OFF**
(otherwise Telegram only shows her tagged/command messages, so "Ria" alone won't trigger). After changing it, remove and re-add the bot in existing groups.

**Stickers.** Ria sometimes (owner-set chance, default 15%, never twice in a row) follows a reply with a sticker from the library — matching the emoji in her reply when possible.
The library starts **empty**: add stickers/packs from the owner panel (below).

**Owner panel.** Send `/owner` (or `/panel`) to the bot in a private chat. Only numeric ids in `OWNER_USER_IDS` can open it (admins cannot)
(usernames are never trusted: they can change). Buttons: 📊 Stats · ⚙️ Controls (bot on/off, DM replies, group replies, stickers on/off, sticker chance — saved in MongoDB, instant) ·
📣 Broadcast (DMs / Groups / Both, preview + confirm + Stop button, throttled, auto-skips blocked users) · ✉️ DM a user (id or @username) · 👥 Message a group ·
🎭 Stickers (add sticker, add whole pack, remove sticker, remove pack, list) · 🚫 Ban/Unban · 🗂 Groups (enable/disable Ria per group).
To add stickers: Stickers → *Add pack* → send any sticker from that pack. `/cancel` aborts any pending step.
You need AAKASH's **numeric** Telegram id (from @userinfobot) in `OWNER_USER_IDS` — `@Advik_prakashh` is shown in the panel header but is not used for authorisation.

**Speed.** Defaults are now `AI_MAX_TOKENS=60`, `AI_CONTEXT_LENGTH=2048`, `HISTORY_MESSAGES=8`, `AI_TEMPERATURE=0.7` (shorter prompt + shorter answers = faster on CPU).
If your VPS `.env` already exists, those old values stay until you change them:

```bash
cd /opt/ria
sudo sed -i 's/^AI_MAX_TOKENS=.*/AI_MAX_TOKENS=60/; s/^AI_CONTEXT_LENGTH=.*/AI_CONTEXT_LENGTH=2048/; s/^AI_TEMPERATURE=.*/AI_TEMPERATURE=0.7/; s/^HISTORY_MESSAGES=.*/HISTORY_MESSAGES=8/; s/^HISTORY_CHAR_BUDGET=.*/HISTORY_CHAR_BUDGET=3000/' .env
grep -q '^OWNER_NAME=' .env || printf '\nOWNER_USER_IDS=\nOWNER_NAME=AAKASH\nOWNER_USERNAME=Advik_prakashh\nGROUP_RATE_LIMIT_MESSAGES=12\n' | sudo tee -a .env >/dev/null
sudo chown root:ria .env && sudo chmod 640 .env
git pull --ff-only && source venv/bin/activate && pip install -r requirements.txt && deactivate
sudo systemctl restart ria && sudo systemctl status ria --no-pager
```

**Chat quality (v2.1).** Ria now remembers a user's gender when they say it ("m ladka hu", "i am a girl") or set `/gender boy|girl`, and talks to them with the right grammar
(she never mixes herself and the user: no "kya kar rahi hu tum"); with unknown gender she avoids gendered verbs. Replies that come out as English are detected and retried once in Hinglish.
Boring replies ("kuch nhi", "acha") make her tease and start a topic instead of echoing, and unclear messages get "kya matlab? clear batao na".
**Try and tune her without Telegram** (uses your real Ollama and the same pipeline, nothing saved):
`cd /opt/ria && source venv/bin/activate && python scripts/try_chat.py` — then edit `app/personality.py` (rules + the few-shot examples at the bottom, which matter most for a 4B model), restart, repeat.
Gemma 3 4B on CPU is a small model: it won't match a large cloud model's consistency even with good prompts. Expect improvement, not perfection; if some replies are still weak, send me the exact chat and I'll add targeted examples.

**About a Hugging Face token already in `.env`.** RIA's VPS `.env` has no HF token: its only HF lines are the blank `HF_REPLICA_*` ones (replica off), and unknown lines are ignored.
Check with `grep -n HF /opt/ria/.env`. A Hugging Face *write* token belongs only in GitHub → Secrets → `HF_TOKEN` (for the Space deploy), never in the VPS `.env` or in chats; if you don't recognise it, delete that line (and revoke the token at huggingface.co/settings/tokens if you're unsure where it came from).

**`/start` screen (v2.2).** `/start` shows a card (your real message and memory counts) with buttons: 🍀 Ria features · 👥 Groups · 💸 Promoter · 📢 Updates · 🎮 Games (coming soon) · ➕ Add me to your group.
The **👑 Owner panel** button appears only for ids in `OWNER_USER_IDS`; admins and everyone else never see it. Optional `.env`: `PROMOTER_URL` (default: the owner's @username link), `UPDATES_URL` (button hidden if empty).

**Continuing old chats (v2.2).** Memory now has three layers, all in MongoDB and all deleted by `/forget`:
recent messages (history, kept `CONVERSATION_RETENTION_DAYS=90` days) · short fact memories (extracted every 4 messages) · a rolling summary of the chat (refreshed every 10 messages) that is fed back into the prompt, so after days she can pick up where you stopped.
A stated name ("mera naam Rohan hai") is saved instantly. `/reset` clears chat history and the summary but keeps fact memories. Summaries and facts are made by your local Gemma only, and lines with passwords/IDs/etc. are skipped.
Update an existing `.env`:

```bash
cd /opt/ria
sudo sed -i 's/^CONVERSATION_RETENTION_DAYS=.*/CONVERSATION_RETENTION_DAYS=90/; s/^MEMORY_EXTRACT_EVERY_N_MESSAGES=.*/MEMORY_EXTRACT_EVERY_N_MESSAGES=4/' .env
grep -q '^SUMMARY_EVERY_N_MESSAGES=' .env || printf 'SUMMARY_EVERY_N_MESSAGES=10\nPROMOTER_URL=\nUPDATES_URL=\n' | sudo tee -a .env >/dev/null
nano .env   # OWNER_USER_IDS=<AAKASH numeric id>  (admins no longer open the panel)
git pull --ff-only && source venv/bin/activate && pip install -r requirements.txt && deactivate && sudo systemctl restart ria
```

**Secretary mode (Telegram Business).** Ria can answer private chats of *your own Telegram account* while you're away (needs Telegram Premium on that account).
1. @BotFather → your bot → *Bot Settings* → **Business Mode** → turn on.
2. Telegram → *Settings → Business → Chatbots* → add the bot. Choose **All private chats except…** (and list the chats Ria must NOT touch) or **Only selected chats**.
3. Permissions: grant **Read Messages**, **Reply to Messages**, **Mark Messages As Read**. Leave **Delete Sent/Received Messages** and Manage-style permissions OFF; Ria never deletes anything.
Behaviour: she replies as Ria (not pretending to be you; if someone asks for you she says you're busy and she'll pass it on). When *you* write in a chat yourself she stays quiet there for `SECRETARY_PAUSE_MINUTES` (default 10).
Owner panel → ⚙️ Controls → *Secretary mode* switches it on/off instantly; the Stats screen shows connected accounts. Chat include/exclude lists are managed in Telegram itself, not by the bot.
Needs python-telegram-bot ≥ 21.6 (already pinned). After `git pull`, restart; no other change is required.

**v2.3 changes.**
- **Honest answers about AI.** Short sincere questions ("kya tum ai ho", "which ai model") get a fixed, instant, in-voice line that says she is an AI called Ria, never a denial and never an invented model name. She never brings the topic up herself. I will not make her claim to be human.
- **Everything is a button.** `/start` is the only command shown; Features, Games (Truth/Dare/Would you rather/Shayari), Meri yaadein, Settings (language, boy/girl, name), Web chat code, About & Privacy are all menus.
  Stickers get a natural reaction (and sometimes a sticker back). Name-based grammar: common names (e.g. AAKASH) start with masculine grammar until the user says otherwise.
- **Memory is always on.** Users can no longer switch memory off or delete their data from the bot; chats are kept forever (`CONVERSATION_RETENTION_DAYS=0`, `MAX_STORED_MESSAGES_PER_USER=50000`) and the About screen tells users this. Deleting on request is an owner-panel action (🧹 Delete user data); keep honouring such requests, privacy laws (DPDP/GDPR) require it.
  The web API still has its own reset/forget endpoints; remove them in `app/api/server.py` if you want those gone too.
- **Self-improvement, honestly.** In the background Ria keeps adding fact memories and a rolling summary per user, so she gets more personal over time. Gemma's weights are NOT trained by chatting (no CPU VPS can do that). Owner panel → 📦 Export data gives a pseudonymous JSONL of private chats (sensitive lines, groups and secretary chats excluded) you can fine-tune with on a GPU machine or mine for better few-shot examples.
- **Retention.** 🔥 daily streak on the home card, games, and gentle "miss you" nudges to users inactive 2+ days (max 3 unanswered, 3 days apart, off switch in Controls → Nudges).
- **Secretary mode fixed.** In business chats Ria now introduces herself ("Main Ria hu, Aakash ki assistant"), answers with a dedicated assistant prompt (never pretends to be you, says you're busy, stays calm if the person is rude), answers one message at a time (no more "pehle wale ka reply aa raha hai") and stays silent instead of sending error texts. Each message is also DM'd to you (`SECRETARY_NOTIFY_OWNER=false` to stop).

Update an existing `.env`:

```bash
cd /opt/ria
sudo sed -i 's/^CONVERSATION_RETENTION_DAYS=.*/CONVERSATION_RETENTION_DAYS=0/; s/^MAX_STORED_MESSAGES_PER_USER=.*/MAX_STORED_MESSAGES_PER_USER=50000/' .env
grep -q '^SECRETARY_NOTIFY_OWNER=' .env || echo 'SECRETARY_NOTIFY_OWNER=true' | sudo tee -a .env >/dev/null
git pull --ff-only && source venv/bin/activate && pip install -r requirements.txt && deactivate && sudo systemctl restart ria
```

## License
MIT (see `LICENSE`).
