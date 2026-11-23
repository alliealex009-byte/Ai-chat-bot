"""Optional typed commands (/memory /language /settings /name /gender /link /health). Everything is also a button in /start."""
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


async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Read-only list of what Ria remembers (memories are always kept so chats can continue)."""
    mems = await _ctx(context).memories.list(update.effective_user.id)
    if not mems:
        return await safe_reply(update.message, "Abhi mujhe tumhare baare mein kuch khaas yaad nahi hai. Baatein karte hain, phir yaad rakhungi 😊")
    await safe_reply(update.message, "Mujhe tumhare baare mein ye yaad hai:\n" + "\n".join(f"{i}. {m['text']}" for i, m in enumerate(mems, 1)))


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(LANG_LABELS[l], callback_data=f"lang:{l}")] for l in VALID_LANGUAGES])
    await update.message.reply_text("Kaunsi bhasha mein baat karein?", reply_markup=kb)


async def _settings_text(ctx, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    u = await ctx.users.get_or_create(uid)
    text = (
        "Tumhari settings:\n"
        f"🗣 Language: {LANG_LABELS.get(u.get('language'), u.get('language'))}\n"
        f"📛 Naam: {u.get('preferred_name') or u.get('first_name') or '-'}\n"
        f"💬 Messages: {u.get('message_count', 0)}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Language", callback_data="lang:menu")]])
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
    if data == "lang:menu":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(LANG_LABELS[l], callback_data=f"lang:{l}")] for l in VALID_LANGUAGES])
        await q.edit_message_text("Kaunsi bhasha mein baat karein?", reply_markup=kb)
    elif data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        await ctx.users.get_or_create(uid)
        if await ctx.users.set_language(uid, lang):
            await q.edit_message_text(f"Done! Ab {LANG_LABELS[lang]} mein baat karenge ✅")
