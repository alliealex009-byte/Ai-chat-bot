"""/start, /help, /about."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.tg.utils import safe_reply

START_TEXT = (
    "Hieee {name}! Main RIA hu 💗\n"
    "Tumhari AI dost — baatein karne, hasane aur sunne ke liye. Hinglish mein masti karte hain!\n\n"
    "Bas kuch bhi likho, main reply karungi. Commands ke liye /help dekho."
)

HELP_TEXT = (
    "Main kya kar sakti hu:\n"
    "💬 Normal chat — Hindi, English ya Hinglish, jo bhi chalega\n"
    "🧠 Tumhari kuch baatein yaad rakhti hu (sirf jo tum batate ho)\n\n"
    "Commands:\n"
    "/start — intro\n"
    "/help — ye list\n"
    "/reset — current baatein clear (memories safe)\n"
    "/memory — jo mujhe yaad hai (delete/edit bhi: /memory delete 2)\n"
    "/forget — tumhara saara data delete\n"
    "/language — bhasha chuno\n"
    "/settings — tumhari settings\n"
    "/name <naam> — main tumhe kis naam se bulau\n"
    "/link — web chat ke liye one-time code\n"
    "/about — mere baare mein"
)

ABOUT_TEXT = (
    "Main RIA hu — ek AI companion 🤖💗\n"
    "Main ek 21 saal ki Indian Gen-Z ladki ka fictional character hu, par asli insaan nahi hu: "
    "meri koi body ya real life nahi hai, bas baatein hain.\n"
    "Mera dimag Gemma 3 4B model hai, jo ek private server par chalta hai.\n"
    "Tumhari baatein sirf is chat ki yaad ke liye store hoti hain, aur /forget se kabhi bhi delete kar sakte ho.\n"
    "Main commands run nahi karti, na internet browse karti hu."
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
