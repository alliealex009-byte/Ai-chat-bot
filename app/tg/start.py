"""/start, /help, /about."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.tg.utils import safe_reply

START_TEXT = "Hieee {name}! Main Ria hu 💗\nBas kuch bhi likho, baatein karte hain. /help dekh lo agar kuch puchna ho 😄"

FEATURES_TEXT = (
    "🍀 Ria kya kya karti hai\n\n"
    "💬 Hinglish mein masti wali chat — DM aur groups dono mein\n"
    "🧠 Tumhari baatein yaad rakhti hu (/memory dekho, /forget se delete)\n"
    "👥 Group mein \"Ria\" bolo ya tag/reply karo, main aa jaungi\n"
    "🎭 Stickers, emojis aur thodi si flirty vibes (limit mein 😌)\n"
    "🌐 Web chat: /link se code lo, same chat wahan bhi\n"
    "⚙️ /language /name /gender /settings se apne hisaab se set karo"
)
GROUPS_TEXT = (
    "👥 Groups mein\n\n"
    "Mujhe group mein add karo (neeche wala button), phir mera naam lo, mujhe tag karo ya mere message pe reply karo.\n"
    "Group ke liye admin ko /start ki zarurat nahi — bas add karo 💗"
)
GAMES_TEXT = "🎮 Games jaldi aa rahe hain! Abhi sirf chat 😄"

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
    "/gender boy|girl — kaise baat karu\n"
    "/link — web chat ke liye one-time code\n"
    "/about — mere baare mein\n\n"
    "Groups mein mera naam lo ya mujhe tag karo, main reply karungi 😌"
)

ABOUT_TEXT = (
    "Main Ria hu 💗 19, Delhi vibes, college, chai aur gossip.\n"
    "Waise honesty se: main ek AI chat companion hu, insaan nahi — par masti poori real hai 😄\n"
    "Tumhari baatein sirf is chat ki yaad ke liye store hoti hain, /forget se kabhi bhi delete."
)


def start_keyboard(settings, bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    """Baka-style /start buttons. The Owner panel button is shown to OWNER_USER_IDS only (never admins)."""
    promoter = settings.promoter_url or f"https://t.me/{settings.owner_username}"
    rows = [
        [InlineKeyboardButton("🍀 Ria features", callback_data="st:features"),
         InlineKeyboardButton("👥 Groups", callback_data="st:groups")],
        [InlineKeyboardButton("💸 Promoter", url=promoter)],
    ]
    second = []
    if settings.updates_url:
        second.append(InlineKeyboardButton("📢 Updates", url=settings.updates_url))
    second.append(InlineKeyboardButton("🎮 Games", callback_data="st:games"))
    rows.append(second)
    if bot_username:
        rows.append([InlineKeyboardButton("➕ Add me to your group", url=f"https://t.me/{bot_username}?startgroup=true")])
    if user_id in settings.owner_ids:
        rows.append([InlineKeyboardButton("👑 Owner panel", callback_data="own:menu")])
    return InlineKeyboardMarkup(rows)


async def start_text(ctx, user, first_name: str) -> str:
    name = (first_name or "").strip() or "dost"
    doc = await ctx.users.get(user) or {}
    msgs = int(doc.get("message_count", 0))
    mems = await ctx.memories.count(user)
    return (
        f"Hieee {name}! Main Ria hu 💗\n"
        "Delhi se, college wali, chai aur gossip ki shaukeen 😌\n\n"
        f"💬 Messages: {msgs}\n🧠 Memories: {mems}\n🗣 Language: {doc.get('language', ctx.settings.default_language)}\n\n"
        "Bas kuch bhi likho, baatein karte hain!"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    u = update.effective_user
    await ctx.users.get_or_create(u.id, u.first_name or "", u.username or "")
    text = await start_text(ctx, u.id, u.first_name or "")
    await safe_reply(update.message, text,
                     reply_markup=start_keyboard(ctx.settings, getattr(context.bot, "username", "") or "", u.id))


async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    q = update.callback_query
    u = q.from_user
    action = (q.data or "").split(":", 1)[-1]
    back = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="st:back")]])
    if action == "back":
        await q.answer()
        text = await start_text(ctx, u.id, getattr(u, "first_name", "") or "")
        await q.edit_message_text(text, reply_markup=start_keyboard(ctx.settings, getattr(context.bot, "username", "") or "", u.id))
        return
    texts = {"features": FEATURES_TEXT, "groups": GROUPS_TEXT, "games": GAMES_TEXT}
    if action in texts:
        await q.answer()
        await q.edit_message_text(texts[action], reply_markup=back)
    else:
        await q.answer()


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.message, HELP_TEXT)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.message, ABOUT_TEXT)
