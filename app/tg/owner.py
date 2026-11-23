"""Owner panel (inline buttons). Access is by NUMERIC Telegram id only (OWNER_USER_IDS + ADMIN_USER_IDS).

Usernames are never trusted for authorisation: they can change. /owner or /panel opens the menu in a private chat.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.services.broadcast import Blocked, FloodWait, broadcast

log = logging.getLogger(__name__)
MAX_TEXT = 3500

MENU_ROWS = [
    [("📊 Stats", "own:stats"), ("⚙️ Controls", "own:ctl")],
    [("📣 Broadcast", "own:bc"), ("✉️ DM user", "own:dm")],
    [("👥 Group msg", "own:gm"), ("🎭 Stickers", "own:st")],
    [("🚫 Ban / Unban", "own:ban"), ("🗂 Groups", "own:groups")],
    [("📦 Export data", "own:export"), ("🧹 Delete user data", "own:wipe")],
    [("✖️ Close", "own:close")],
]
BACK = [("⬅️ Menu", "own:menu")]


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


def _ctx(context):
    return context.application.bot_data["ctx"]


def _is_owner(ctx, user_id: int) -> bool:
    return user_id in ctx.settings.owner_ids


def _header(ctx) -> str:
    s = ctx.settings
    return f"👑 Ria owner panel\nOwner: {s.owner_name} (@{s.owner_username})"


def _on(v: bool) -> str:
    return "ON ✅" if v else "OFF ⛔"


def _secs(x) -> float:
    return x.total_seconds() if hasattr(x, "total_seconds") else float(x)


def _convert(e: Exception) -> None:
    """Map Telegram errors to the transport-agnostic exceptions used by services.broadcast."""
    from telegram.error import BadRequest, Forbidden, RetryAfter

    if isinstance(e, RetryAfter):
        raise FloodWait(_secs(e.retry_after))
    if isinstance(e, Forbidden):
        raise Blocked()
    if isinstance(e, BadRequest) and any(k in str(e).lower() for k in ("chat not found", "user not found", "deactivated")):
        raise Blocked()
    raise e


# -- commands ----------------------------------------------------------------------------------
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    if not _is_owner(ctx, update.effective_user.id):
        return  # silently ignore everyone else
    ctx.owner_state.pop(update.effective_user.id, None)
    await update.message.reply_text(_header(ctx) + "\n\nKya karna hai?", reply_markup=_kb(MENU_ROWS))


# -- screens -----------------------------------------------------------------------------------
async def _stats_text(ctx) -> str:
    rt = await ctx.runtime.all()
    h = await ctx.health(detailed=True)
    st = ctx.engine.stats
    return (
        f"📊 Stats\nstatus: {h['status']} (ollama {h['ollama']}, mongo {h['mongo']})\n"
        f"users: {await ctx.users.count()} | groups: {await ctx.chats.count()} | stickers: {await ctx.stickers.count()}\n"
        f"messages: {st['messages']} (groups {st['group_messages']}) | ok {st['ok']} | errors {st['errors']} | busy {st['busy']}\n"
        f"queue: {h['queue']['queued']} waiting / {h['queue']['active']} running\n"
        f"latency avg/p95: {h['latency']['avg_ms']}/{h['latency']['p95_ms']} ms\n"
        f"banned users: {len(ctx.banned)} | secretary accounts: {await ctx.business.count_active()}\n"
        f"bot {_on(rt['bot_enabled'])} | DM {_on(rt['dm_enabled'])} | groups {_on(rt['group_enabled'])} | "
        f"stickers {_on(rt['stickers_enabled'])} ({rt['sticker_chance']}%)"
    )


async def _controls(ctx):
    rt = await ctx.runtime.all()
    rows = [
        [(f"Bot: {_on(rt['bot_enabled'])}", "own:tg:bot_enabled")],
        [(f"DM replies: {_on(rt['dm_enabled'])}", "own:tg:dm_enabled"), (f"Groups: {_on(rt['group_enabled'])}", "own:tg:group_enabled")],
        [(f"Stickers: {_on(rt['stickers_enabled'])}", "own:tg:stickers_enabled"), (f"Chance: {rt['sticker_chance']}%", "own:chance")],
        [(f"Secretary mode: {_on(rt['secretary_enabled'])}", "own:tg:secretary_enabled"), (f"Nudges: {_on(rt['nudges_enabled'])}", "own:tg:nudges_enabled")],
        BACK,
    ]
    return "⚙️ Controls (changes apply instantly, saved in DB)", _kb(rows)


async def _groups_screen(ctx):
    groups = await ctx.chats.groups(20)
    if not groups:
        return "Abhi koi group nahi mila. Bot ko group mein add karo aur wahan kuch likho.", _kb([BACK])
    rows = [[(f"{'✅' if g.get('enabled', True) else '⛔'} {g.get('title') or g['_id']}"[:40], f"own:gtog:{g['_id']}")] for g in groups]
    rows.append(BACK)
    return "🗂 Groups (tap to enable/disable Ria there)", _kb(rows)


# -- callbacks ---------------------------------------------------------------------------------
async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    q = update.callback_query
    uid = q.from_user.id
    if not _is_owner(ctx, uid):
        await q.answer("Not allowed", show_alert=True)
        return
    await q.answer()
    parts = (q.data or "").split(":")
    act = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    async def show(text: str, rows=None):
        await q.edit_message_text(text, reply_markup=_kb(rows if rows is not None else [BACK]))

    if act == "menu":
        ctx.owner_state.pop(uid, None)
        await show(_header(ctx) + "\n\nKya karna hai?", MENU_ROWS)
    elif act == "close":
        ctx.owner_state.pop(uid, None)
        await q.message.delete()
    elif act == "stats":
        await show(await _stats_text(ctx))
    elif act == "ctl":
        text, kb = await _controls(ctx)
        await q.edit_message_text(text, reply_markup=kb)
    elif act == "tg" and arg in ("bot_enabled", "dm_enabled", "group_enabled", "stickers_enabled", "secretary_enabled", "nudges_enabled"):
        await ctx.runtime.toggle(arg)
        text, kb = await _controls(ctx)
        await q.edit_message_text(text, reply_markup=kb)
    elif act == "chance":
        await ctx.runtime.cycle_chance()
        text, kb = await _controls(ctx)
        await q.edit_message_text(text, reply_markup=kb)
    elif act == "bc":
        await show("📣 Broadcast kisko bhejna hai?",
                   [[("👤 DMs", "own:bct:dm"), ("👥 Groups", "own:bct:groups")], [("🌍 Both", "own:bct:both")], BACK])
    elif act == "bct" and arg in ("dm", "groups", "both"):
        ctx.owner_state[uid] = {"action": "bc_text", "target": arg}
        await show(f"📣 Target: {arg}\nAb message bhejo (text, max {MAX_TEXT} chars). /cancel se rukna.", [BACK])
    elif act == "bcgo":
        await _start_broadcast(ctx, context, q, uid)
    elif act == "bcstop":
        if ctx.broadcast_cancel:
            ctx.broadcast_cancel.set()
        await q.edit_message_text("🛑 Stopping broadcast…")
    elif act == "dm":
        ctx.owner_state[uid] = {"action": "dm_who"}
        await show("✉️ User ka numeric id ya @username bhejo. /cancel se rukna.")
    elif act == "gm":
        groups = await ctx.chats.groups(20)
        if not groups:
            await show("Koi group nahi mila.")
        else:
            rows = [[((g.get("title") or str(g["_id"]))[:40], f"own:gmsel:{g['_id']}")] for g in groups] + [BACK]
            await show("👥 Kis group mein bhejna hai?", rows)
    elif act == "gmsel" and arg.lstrip("-").isdigit():
        ctx.owner_state[uid] = {"action": "gm_text", "chat": int(arg)}
        await show("Ab message bhejo. /cancel se rukna.")
    elif act == "st":
        await _sticker_menu(ctx, q, uid, arg)
    elif act == "ban":
        ctx.owner_state[uid] = {"action": "ban_who"}
        await show("🚫 User ka numeric id ya @username bhejo (ban/unban toggle). /cancel se rukna.")
    elif act == "export":
        await _export(ctx, context, q)
    elif act == "wipe":
        ctx.owner_state[uid] = {"action": "wipe_who"}
        await show("🧹 Jis user ka saara data delete karna hai uska numeric id ya @username bhejo (sirf user ki request pe!). /cancel se rukna.")
    elif act == "wipego" and ctx.owner_state.get(uid, {}).get("action") == "wipe_confirm":
        target = ctx.owner_state.pop(uid)["user"]
        res = await ctx.engine.forget(target)
        await show(f"🧹 User {target}: {res['messages']} messages aur {res['memories']} memories delete ho gayi.")
    elif act == "groups":
        text, kb = await _groups_screen(ctx)
        await q.edit_message_text(text, reply_markup=kb)
    elif act == "gtog" and arg.lstrip("-").isdigit():
        doc = await ctx.chats.get(int(arg))
        if doc:
            await ctx.chats.set_enabled(int(arg), not doc.get("enabled", True))
        text, kb = await _groups_screen(ctx)
        await q.edit_message_text(text, reply_markup=kb)
    elif act == "bccancel":
        ctx.owner_state.pop(uid, None)
        await show("Cancelled ✅", [BACK])


async def _sticker_menu(ctx, q, uid: int, arg: str) -> None:
    if arg == "":
        n = await ctx.stickers.count()
        rows = [[("➕ Add sticker", "own:st:add"), ("📦 Add pack", "own:st:addpack")],
                [("➖ Remove sticker", "own:st:rm"), ("🗑 Remove pack", "own:st:rmpack")],
                [("📋 List", "own:st:list")], BACK]
        await q.edit_message_text(f"🎭 Stickers ({n} saved)", reply_markup=_kb(rows))
    elif arg == "list":
        packs = await ctx.stickers.packs()
        text = "\n".join(f"• {name}: {cnt}" for name, cnt in sorted(packs.items())) or "Koi sticker nahi hai."
        await q.edit_message_text("📋 Sticker packs\n" + text, reply_markup=_kb([[("⬅️ Back", "own:st")], BACK]))
    elif arg in ("add", "addpack", "rm", "rmpack"):
        ctx.owner_state[uid] = {"action": f"st_{arg}"}
        hint = {"add": "Ek ya zyada stickers bhejo (ek ek karke).", "addpack": "Us pack ka koi ek sticker bhejo, poora pack add hoga.",
                "rm": "Jo sticker hatana hai wo bhejo.", "rmpack": "Us pack ka koi ek sticker bhejo, poora pack hatega."}[arg]
        await q.edit_message_text(f"🎭 {hint}\n/cancel se rukna.", reply_markup=_kb([BACK]))


async def _start_broadcast(ctx, context, q, uid: int) -> None:
    st = ctx.owner_state.get(uid)
    if not st or st.get("action") != "bc_confirm":
        await q.edit_message_text("Kuch pending nahi hai.", reply_markup=_kb([BACK]))
        return
    if ctx.broadcast_cancel is not None:
        await q.edit_message_text("Ek broadcast already chal raha hai.", reply_markup=_kb([BACK]))
        return
    ctx.owner_state.pop(uid, None)
    targets = await _targets(ctx, st["target"])
    await q.edit_message_text(f"📣 Broadcast start: {len(targets)} chats…", reply_markup=_kb([[("🛑 Stop", "own:bcstop")]]))
    task = asyncio.create_task(_run_broadcast(ctx, context.bot, q.message.chat_id, targets, st["text"]))
    ctx.owner_tasks.add(task)
    task.add_done_callback(ctx.owner_tasks.discard)


async def _targets(ctx, target: str) -> list[int]:
    ids: list[int] = []
    if target in ("dm", "both"):
        ids += await ctx.users.broadcast_ids()
    if target in ("groups", "both"):
        for g in await ctx.chats.groups(5000):
            if g.get("enabled", True):
                ids.append(g["_id"])
    return list(dict.fromkeys(ids))


async def _run_broadcast(ctx, bot, owner_chat: int, targets: list[int], text: str) -> None:
    cancel = asyncio.Event()
    ctx.broadcast_cancel = cancel

    async def send(cid: int) -> None:
        try:
            await bot.send_message(cid, text)
        except Exception as e:  # noqa: BLE001
            _convert(e)

    async def on_blocked(cid: int) -> None:
        if cid > 0:
            await ctx.users.set_blocked(cid, True)
        else:
            await ctx.chats.set_active(cid, False)

    try:
        res = await broadcast(targets, send, on_blocked, cancel)
        note = " (stopped)" if res["cancelled"] else ""
        await bot.send_message(owner_chat, f"📣 Broadcast done{note}: sent {res['sent']}/{res['total']}, "
                                           f"blocked {res['blocked']}, failed {res['failed']}")
    except Exception as e:  # noqa: BLE001
        log.error("broadcast crashed: %s", type(e).__name__)
        await bot.send_message(owner_chat, "Broadcast mein error aa gaya, logs check karo.")
    finally:
        ctx.broadcast_cancel = None


# -- owner's typed/sticker input for pending actions ----------------------------------------------
async def _export(ctx, context, q) -> None:
    import os
    from datetime import datetime

    from app.services.dataset import build_dataset

    path = os.path.join("data", "exports", f"ria_dataset_{datetime.now().strftime('%Y%m%d_%H%M')}.jsonl")
    info = await build_dataset(ctx, path)
    with open(path, "rb") as f:
        await context.bot.send_document(
            chat_id=q.message.chat_id, document=f, filename=os.path.basename(path),
            caption=f"📦 {info['users']} users, {info['rows']} chat windows, {info['messages']} messages (pseudonymous, private chats only)")
    await q.edit_message_text("📦 Dataset bhej diya ✅", reply_markup=_kb([BACK]))


async def _resolve_user(ctx, raw: str) -> Optional[int]:
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    doc = await ctx.users.find_by_username(raw)
    return doc["_id"] if doc else None


async def owner_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    msg, uid = update.message, update.effective_user.id
    st = ctx.owner_state.get(uid)
    if not st or not _is_owner(ctx, uid):
        return  # normal chat flow continues
    text = (msg.text or "").strip()
    if text.lower() in ("/cancel", "cancel"):
        ctx.owner_state.pop(uid, None)
        await msg.reply_text("Cancelled ✅", reply_markup=_kb([BACK]))
        raise ApplicationHandlerStop
    if text.startswith("/"):
        return  # let other commands (e.g. /owner) run normally
    action = st["action"]
    sticker = msg.sticker

    if action == "bc_text" and text:
        if len(text) > MAX_TEXT:
            await msg.reply_text(f"Bahut lamba hai (max {MAX_TEXT}).")
        else:
            n = len(await _targets(ctx, st["target"]))
            ctx.owner_state[uid] = {"action": "bc_confirm", "target": st["target"], "text": text}
            await msg.reply_text(f"📣 Preview ({n} chats, target: {st['target']}):\n\n{text}",
                                 reply_markup=_kb([[("✅ Send", "own:bcgo"), ("❌ Cancel", "own:bccancel")]]))
    elif action == "dm_who" and text:
        target = await _resolve_user(ctx, text)
        if target is None:
            await msg.reply_text("User nahi mila. Numeric id bhejo.")
        else:
            ctx.owner_state[uid] = {"action": "dm_text", "user": target}
            await msg.reply_text(f"✉️ User {target} ko kya bhejna hai? (text)")
    elif action in ("dm_text", "gm_text") and text:
        dest = st["user"] if action == "dm_text" else st["chat"]
        try:
            await context.bot.send_message(dest, text[:MAX_TEXT])
            await msg.reply_text("Sent ✅", reply_markup=_kb([BACK]))
        except Exception as e:  # noqa: BLE001
            await msg.reply_text(f"Send nahi hua: {type(e).__name__}", reply_markup=_kb([BACK]))
        ctx.owner_state.pop(uid, None)
    elif action == "wipe_who" and text:
        target = await _resolve_user(ctx, text)
        if target is None:
            await msg.reply_text("User nahi mila.")
        else:
            ctx.owner_state[uid] = {"action": "wipe_confirm", "user": target}
            await msg.reply_text(f"Pakka? User {target} ki saari chat, memories aur profile hamesha ke liye delete hongi.",
                                 reply_markup=_kb([[("✅ Haan, delete", "own:wipego"), ("❌ Nahi", "own:menu")]]))
    elif action == "ban_who" and text:
        target = await _resolve_user(ctx, text)
        if target is None:
            await msg.reply_text("User nahi mila.")
        elif target in ctx.settings.owner_ids:
            await msg.reply_text("Owner ko ban nahi kar sakte 😄")
        else:
            now_banned = target not in ctx.banned
            await ctx.users.set_banned(target, now_banned)
            (ctx.banned.add if now_banned else ctx.banned.discard)(target)
            ctx.owner_state.pop(uid, None)
            await msg.reply_text(f"User {target}: {'BANNED 🚫' if now_banned else 'unbanned ✅'}", reply_markup=_kb([BACK]))
    elif action.startswith("st_") and sticker:
        await _handle_sticker(ctx, context, msg, uid, action, sticker)
    else:
        await msg.reply_text("Abhi ye nahi chahiye. Sahi cheez bhejo ya /cancel.")
    raise ApplicationHandlerStop


async def _handle_sticker(ctx, context, msg, uid: int, action: str, sticker) -> None:
    if action == "st_add":
        new = await ctx.stickers.add(sticker.file_unique_id, sticker.file_id, sticker.emoji or "", sticker.set_name or "")
        await msg.reply_text(("Added ✅" if new else "Already tha, update kar diya ✅") + "  Aur bhejo ya /cancel.")
    elif action == "st_addpack":
        if not sticker.set_name:
            await msg.reply_text("Is sticker ka pack nahi hai, single add ke liye 'Add sticker' use karo.")
            return
        try:
            pack = await context.bot.get_sticker_set(sticker.set_name)
        except Exception as e:  # noqa: BLE001
            await msg.reply_text(f"Pack nahi mila: {type(e).__name__}")
            return
        items = [{"unique_id": s.file_unique_id, "file_id": s.file_id, "emoji": s.emoji or "", "set_name": pack.name}
                 for s in pack.stickers[:200]]
        n = await ctx.stickers.add_many(items)
        ctx.owner_state.pop(uid, None)
        await msg.reply_text(f"📦 Pack '{pack.name}': {n} new stickers added ({len(items)} total in pack).", reply_markup=_kb([BACK]))
    elif action == "st_rm":
        ok = await ctx.stickers.remove(sticker.file_unique_id)
        await msg.reply_text("Removed ✅" if ok else "Ye library mein nahi tha.")
    elif action == "st_rmpack":
        n = await ctx.stickers.remove_pack(sticker.set_name or "")
        ctx.owner_state.pop(uid, None)
        await msg.reply_text(f"🗑 {n} stickers removed.", reply_markup=_kb([BACK]))
