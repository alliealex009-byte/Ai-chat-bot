"""User commands: /reset /memory /forget /language /settings /name /link /health."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.ai.prompts import is_sensitive
from app.database.users import VALID_LANGUAGES
from app.tg.utils import safe_reply

log = logging.getLogger(__name__)

LANG_LABELS = {"hinglish": "Hinglish 🇮🇳", "hindi": "Hindi (Roman)", "english": "English"}


def _ctx(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["ctx"]


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = await _ctx(context).engine.reset(update.effective_user.id)
    await safe_reply(update.message, "Done! Naye sire se shuru karte hain 🙌 (Tumhari memories safe hain, unhe hatane ke liye /forget.)")


async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    uid = update.effective_user.id
    args = context.args or []
    mems = await ctx.memories.list(uid)

    if args and args[0].lower() in ("delete", "del", "edit", "add"):
        action = args[0].lower()
        if action == "add":
            text = " ".join(args[1:]).strip()
            if not text:
                return await safe_reply(update.message, "Aise likho: /memory add Mujhe cricket pasand hai")
            if is_sensitive(text):
                return await safe_reply(update.message, "Isme private info lag rahi hai (password/number/email). Wo main yaad nahi rakhungi 🙅‍♀️")
            await ctx.memories.upsert(uid, text, source="user")
            return await safe_reply(update.message, "Yaad kar liya ✅")
        try:
            idx = int(args[1]) - 1
            target = mems[idx]
        except (IndexError, ValueError):
            return await safe_reply(update.message, "Sahi number do. Pehle /memory se list dekho.")
        if action in ("delete", "del"):
            await ctx.memories.delete_one(uid, target["_id"])
            return await safe_reply(update.message, "Bhula diya ✅")
        new_text = " ".join(args[2:]).strip()
        if not new_text:
            return await safe_reply(update.message, "Aise likho: /memory edit 2 naya text")
        if is_sensitive(new_text):
            return await safe_reply(update.message, "Isme private info lag rahi hai, wo store nahi karungi 🙅‍♀️")
        await ctx.memories.update_text(uid, target["_id"], new_text)
        return await safe_reply(update.message, "Update kar diya ✅")

    if not mems:
        return await safe_reply(update.message, "Abhi mujhe tumhare baare mein kuch khaas yaad nahi hai. Baatein karte hain, phir yaad rakhungi 😊")
    lines = [f"{i}. {m['text']}" for i, m in enumerate(mems, 1)]
    await safe_reply(
        update.message,
        "Mujhe tumhare baare mein ye yaad hai:\n" + "\n".join(lines)
        + "\n\nHatane ke liye: /memory delete <number>\nBadalne ke liye: /memory edit <number> <text>\nSab delete: /forget",
    )


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Haan, sab delete karo", callback_data="forget:yes"),
        InlineKeyboardButton("Nahi", callback_data="forget:no"),
    ]])
    await update.message.reply_text(
        "Pakka? Tumhari saari chat history, memories aur settings hamesha ke liye delete ho jayengi.", reply_markup=kb
    )


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(LANG_LABELS[l], callback_data=f"lang:{l}")] for l in VALID_LANGUAGES])
    await update.message.reply_text("Kaunsi bhasha mein baat karein?", reply_markup=kb)


async def _settings_text(ctx, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    u = await ctx.users.get_or_create(uid)
    mem_on = u.get("memory_enabled", True)
    text = (
        "Tumhari settings:\n"
        f"🗣 Language: {LANG_LABELS.get(u.get('language'), u.get('language'))}\n"
        f"📛 Naam: {u.get('preferred_name') or u.get('first_name') or '-'}\n"
        f"🧠 Memory: {'ON' if mem_on else 'OFF'}\n"
        f"🗓 History retention: {ctx.settings.conversation_retention_days} din\n"
        f"💬 Messages: {u.get('message_count', 0)}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Memory OFF karo" if mem_on else "Memory ON karo", callback_data=f"mem:{'off' if mem_on else 'on'}"),
        InlineKeyboardButton("Language", callback_data="lang:menu"),
    ]])
    return text, kb


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = await _settings_text(_ctx(context), update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb)


async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    new = " ".join(context.args or []).strip()
    if not new:
        return await safe_reply(update.message, "Aise likho: /name Rahul")
    if is_sensitive(new) or len(new) > 40:
        return await safe_reply(update.message, "Ye naam thik nahi lag raha, chhota sa naam batao 🙂")
    await ctx.users.get_or_create(update.effective_user.id)
    await ctx.users.set_preferred_name(update.effective_user.id, new)
    await safe_reply(update.message, f"Okayy, ab se {new[:40]} bulaungi 💗")


async def gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/gender boy|girl — tells Ria how to talk to you (grammar only)."""
    ctx = _ctx(context)
    arg = (context.args[0].lower() if context.args else "")
    g = {"boy": "male", "ladka": "male", "male": "male", "girl": "female", "ladki": "female", "female": "female"}.get(arg)
    if not g:
        return await safe_reply(update.message, "Aise likho: /gender boy ya /gender girl")
    await ctx.users.get_or_create(update.effective_user.id, update.effective_user.first_name or "", update.effective_user.username or "")
    await ctx.users.set_gender(update.effective_user.id, g)
    await safe_reply(update.message, "Done, ab se aise hi baat karungi 😄" if g == "male" else "Done 💗 ab se aise hi baat karungi")


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    if not ctx.settings.api_enabled:
        return await safe_reply(update.message, "Web chat abhi band hai.")
    uid = update.effective_user.id
    await ctx.users.get_or_create(uid, update.effective_user.first_name or "", update.effective_user.username or "")
    code = await ctx.web_auth.create_link_code(uid)
    mins = ctx.settings.api_link_code_ttl_seconds // 60
    await safe_reply(
        update.message,
        f"Web chat ka one-time code: {code}\n{mins} minute mein use karo, ek hi baar chalega. Kisi ko share mat karna!\n"
        "Web par same chat history aur memories milengi.",
    )


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _ctx(context)
    uid = update.effective_user.id
    if uid not in ctx.settings.admin_user_ids and uid not in ctx.settings.owner_ids:
        return  # silently ignore non-admins
    h = await ctx.health(detailed=True)
    q = h["queue"]
    await safe_reply(
        update.message,
        f"status: {h['status']}\nollama: {h['ollama']} ({h['model']})\nmongo: {h['mongo']}\n"
        f"queue: {q['queued']} waiting / {q['active']} running (max {q['concurrency']})\n"
        f"latency avg/p95: {h['latency']['avg_ms']}/{h['latency']['p95_ms']} ms\n"
        f"hf_replica: {h['hf_replica']}\nopenrouter: {h['openrouter']}\nuptime: {h['uptime_seconds']}s",
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    ctx = _ctx(context)
    uid = q.from_user.id  # always the pressing user's own id => isolation
    await q.answer()
    data = q.data or ""
    if data == "forget:yes":
        res = await ctx.engine.forget(uid)
        await q.edit_message_text(f"Done 🧹 {res['messages']} messages aur {res['memories']} memories delete ho gayi. Ab hum fresh start kar sakte hain!")
    elif data == "forget:no":
        await q.edit_message_text("Thik hai, kuch delete nahi kiya 😊")
    elif data == "lang:menu":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(LANG_LABELS[l], callback_data=f"lang:{l}")] for l in VALID_LANGUAGES])
        await q.edit_message_text("Kaunsi bhasha mein baat karein?", reply_markup=kb)
    elif data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        await ctx.users.get_or_create(uid)
        if await ctx.users.set_language(uid, lang):
            await q.edit_message_text(f"Done! Ab {LANG_LABELS[lang]} mein baat karenge ✅")
    elif data in ("mem:on", "mem:off"):
        await ctx.users.get_or_create(uid)
        await ctx.users.set_memory_enabled(uid, data == "mem:on")
        text, kb = await _settings_text(ctx, uid)
        await q.edit_message_text(text, reply_markup=kb)
