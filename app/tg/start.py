"""/start, /help, /about."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.tg.utils import safe_reply

START_TEXT = "Hieee {name}! Main Ria hu 💗\nBas kuch bhi likho, baatein karte hain. /help dekh lo agar kuch puchna ho 😄"

HELP_TEXT = (
    "Main Ria hu, bas chat karo 💬\n\n"
    "/start — intro\n"
    "/help — ye list\n"
    "/reset — chat clear (memories safe)\n"
    "/memory — jo mujhe yaad hai (/memory delete 2, /memory edit 2 text, /memory add text)\n"
    "/forget — tumhara saara data delete\n"
    "/language — bhasha chuno\n"
    "/settings — tumhari settings\n"
    "/name <naam> — kis naam se bulau\n"
    "/link — web chat ke liye one-time code\n"
    "/about — mere baare mein\n\n"
    "Groups mein mera naam lo ya mujhe tag karo, main reply karungi 😌"
)

ABOUT_TEXT = (
    "Main Ria hu 💗 19, Delhi vibes, college, chai aur gossip.\n"
    "Waise honesty se: main ek AI chat companion hu, insaan nahi — par masti poori real hai 😄\n"
    "Tumhari baatein sirf is chat ki yaad ke liye store hoti hain, /forget se kabhi bhi delete."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    u = update.effective_user
    await ctx.users.get_or_create(u.id, u.first_name or "", u.username or "")
    await safe_reply(update.message, START_TEXT.format(name=(u.first_name or "").strip() or "dost"))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.message, HELP_TEXT)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.message, ABOUT_TEXT)
