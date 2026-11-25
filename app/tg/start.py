"""/start home screen and every sub-menu (everything is a button; typing commands is optional)."""
from __future__ import annotations

import html
import random

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.database.users import VALID_LANGUAGES
from app.tg.utils import safe_reply

HTML = "HTML"
LANG_LABELS = {"hinglish": "Hinglish 🇮🇳", "hindi": "Hindi (Roman)", "english": "English"}

START_TEXT = "Hieee! Main Ria hu 💗"   # plain fallback

HELP_TEXT = (
    "Main Ria hu, bas chat karo 💬\n\n"
    "Saari cheezein /start ke buttons mein hain: features, games, settings, memories, web chat.\n"
    "Groups mein mera naam lo ya mujhe tag karo, main reply karungi 😌"
)

ABOUT_TEXT = (
    "Main Ria hu 💗 19, Delhi vibes, college, chai aur gossip.\n"
    "Waise honesty se: main ek AI chat companion hu, insaan nahi — par masti poori real hai 😄\n\n"
    "🔒 Privacy: tumhari chat aur yaadein secure database mein store hoti hain taaki main tumhe yaad rakh sakun "
    "aur waqt ke saath behtar ban sakun. Photos save nahi hoti, bas unpe meri reaction yaad rehti hai. Kuch hatwana ho toh owner se kaho."
)

FEATURES_TEXT = (
    "🍀 <b>Ria kya kya karti hai</b>\n\n"
    "💬 Hinglish mein masti wali chat — DM aur groups dono mein\n"
    "🧠 Tumhari baatein yaad rakhti hu, kal wahin se continue karte hain\n"
    "🔥 Daily streak — roz baat karo, streak badhao\n"
    "🎮 Truth, Dare, Would you rather aur shayari\n"
    "👥 Group mein \"Ria\" bolo ya tag/reply karo, main aa jaungi\n"
    "🎭 Stickers, emojis aur thodi si flirty vibes (limit mein 😌)\n"
    "🌐 Web chat — same chat, same yaadein"
)
GROUPS_TEXT = (
    "👥 <b>Groups mein</b>\n\n"
    "Mujhe group mein add karo (neeche wala button), phir mera naam lo, mujhe tag karo ya mere message pe reply karo 💗"
)

# --- games (fixed lists: instant, always clean) ------------------------------------------------------
TRUTH = [
    "Aaj tak ki sabse embarrassing cheez jo tumhare saath hui? 🙈",
    "Last time tumne kisi se jhooth bola, kya tha? 😏",
    "Tumhari sabse weird habit kaunsi hai? 😂",
    "Kaunsa gaana tum chupke se sunte ho aur kisi ko batate nahi? 🎧",
    "Bachpan ka sabse funny darr kya tha? 😅",
    "Agar ek din ke liye invisible ho jao toh sabse pehle kya karoge? 👀",
    "Tumhara sabse bada pet peeve kya hai? 😤",
    "Kaunsi ek cheez tum abhi kharidna chahte ho? 🛍️",
]
DARE = [
    "Apne best friend ko ek funny sticker bhejo abhi 😂",
    "Next 2 minute tak sirf emojis mein baat karo 🙈",
    "Apni gallery ki last selfie ka description likho 🤳",
    "Ek line ki shayari banao mere liye, abhi! ✍️",
    "Chai ya coffee — ek chuno aur 3 reasons do 😌",
    "Apne naam se ek rhyme banao 🎤",
    "Ek glass paani piyo aur batao 💧 (health first!)",
    "Apni favourite movie ka dialogue yahan likho 🎬",
]
WYR = [
    "Would you rather: hamesha late aao ya hamesha 1 ghanta jaldi? ⏰",
    "Would you rather: sirf chai piyo ya sirf coffee, zindagi bhar? ☕",
    "Would you rather: mind reading ya udna? 🦋",
    "Would you rather: har din biryani ya har din pizza? 🍕",
    "Would you rather: phone ke bina 1 hafta ya internet ke bina 1 mahina? 📵",
    "Would you rather: past mein jao ya future mein? ⏳",
    "Would you rather: bahut paisa lekin akela ya kam paisa lekin full masti? 💸",
]
QUOTES = [
    "“Chai thandi ho jaaye toh chalta hai, par mood nahi.” ☕",
    "“Kuch log notification jaise hote hain, aate hain toh din ban jaata hai.” ✨",
    "“Zindagi short hai, story mein daalo aur aage badho.” 😌",
    "“Overthinking ka ilaaj ek achhi si neend hai.” 😴",
    "“Jo tumhe sunta hai, wahi apna hai.” 💗",
    "“Aaj ka plan: kuch nahi. Aur wo bhi poori shiddat se.” 😎",
    "“Smile karo, kya pata koi sach mein dekh raha ho.” 🌸",
]
GAMES = {"truth": ("🎯 Truth", TRUTH), "dare": ("🔥 Dare", DARE), "wyr": ("🤔 Would you rather", WYR),
         "quote": ("💬 Shayari", QUOTES)}


def _home_rows(settings, bot_username: str, user_id: int) -> list[list[Btn]]:
    promoter = settings.promoter_url or f"https://t.me/{settings.owner_username}"
    rows = [
        [Btn("🍀 Features", callback_data="st:features"), Btn("🎮 Games", callback_data="st:games")],
        [Btn("🧠 Meri yaadein", callback_data="st:mem"), Btn("⚙️ Settings", callback_data="st:settings")],
        [Btn("🌐 Web chat", callback_data="st:link"), Btn("👥 Groups", callback_data="st:groups")],
        [Btn("ℹ️ About & Privacy", callback_data="st:about"), Btn("💸 Promoter", url=promoter)],
    ]
    if settings.updates_url:
        rows.append([Btn("📢 Updates", url=settings.updates_url)])
    if bot_username:
        rows.append([Btn("➕ Add me to your group", url=f"https://t.me/{bot_username}?startgroup=true")])
    if user_id in settings.owner_ids:
        rows.append([Btn("👑 Owner panel", callback_data="own:menu")])
    return rows


def start_keyboard(settings, bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    """Owner panel button is shown to OWNER_USER_IDS only (never admins)."""
    return InlineKeyboardMarkup(_home_rows(settings, bot_username, user_id))


async def start_text(ctx, user_id: int, first_name: str) -> str:
    name = html.escape((first_name or "").strip() or "dost")
    doc = await ctx.users.get(user_id) or {}
    msgs, streak = int(doc.get("message_count", 0)), int(doc.get("streak", 0))
    mems = await ctx.memories.count(user_id)
    streak_line = f"🔥 Streak: <b>{streak}</b> din" if streak else "🔥 Streak: aaj se shuru karo!"
    return (
        f"✨ <b>Hieee {name}!</b> ✨\n\n"
        "<blockquote>Main <b>Ria</b> hu 💗\nDelhi ki college girl, chai aur gossip ki shaukeen ☕</blockquote>\n\n"
        f"{streak_line}\n💬 Chats: <b>{msgs}</b>   🧠 Yaadein: <b>{mems}</b>\n\n"
        "<i>“Bas ek ‘hi’ bolo, baaki main sambhal lungi 😌”</i>"
    )


def _back(to: str = "st:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[Btn("⬅️ Back", callback_data=to)]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    u = update.effective_user
    await ctx.users.get_or_create(u.id, u.first_name or "", u.username or "")
    await safe_reply(update.message, await start_text(ctx, u.id, u.first_name or ""), parse_mode=HTML,
                     reply_markup=start_keyboard(ctx.settings, getattr(context.bot, "username", "") or "", u.id))


async def _settings_screen(ctx, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    u = await ctx.users.get_or_create(uid)
    g = {"male": "Boy 👦", "female": "Girl 👧"}.get(u.get("gender"), "Batao na 🙂")
    text = (
        "⚙️ <b>Settings</b>\n\n"
        f"🗣 Language: <b>{LANG_LABELS.get(u.get('language'), u.get('language'))}</b>\n"
        f"📛 Naam: <b>{html.escape(u.get('preferred_name') or u.get('first_name') or '-')}</b>\n"
        f"🧑 Tum: <b>{g}</b>"
    )
    kb = InlineKeyboardMarkup([
        [Btn(("✅ " if u.get("language") == l else "") + LANG_LABELS[l], callback_data=f"st:lang:{l}") for l in VALID_LANGUAGES[:2]],
        [Btn(("✅ " if u.get("language") == "english" else "") + LANG_LABELS["english"], callback_data="st:lang:english")],
        [Btn("👦 Main Boy hu", callback_data="st:gender:male"), Btn("👧 Main Girl hu", callback_data="st:gender:female")],
        [Btn("✏️ Naam badlo", callback_data="st:name")],
        [Btn("⬅️ Back", callback_data="st:home")],
    ])
    return text, kb


async def _memories_screen(ctx, uid: int) -> str:
    mems = await ctx.memories.list(uid)
    if not mems:
        body = "Abhi kuch khaas yaad nahi hai 😊 thodi baatein karte hain, phir yaad rakhungi!"
    else:
        body = "\n".join(f"• {html.escape(m['text'])}" for m in mems[:30])
    return f"🧠 <b>Mujhe tumhare baare mein ye yaad hai</b>\n\n{body}\n\n<i>Ye sab mere paas safe hai, taaki hum kal wahin se baat kar sakein 💗</i>"


async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    q = update.callback_query
    u = q.from_user
    parts = (q.data or "").split(":")
    action, arg = (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")
    await q.answer()

    async def show(text: str, kb: InlineKeyboardMarkup) -> None:
        await q.edit_message_text(text, reply_markup=kb, parse_mode=HTML)

    if action in ("home", "back"):
        ctx.user_state.pop(u.id, None)
        await show(await start_text(ctx, u.id, getattr(u, "first_name", "") or ""),
                   start_keyboard(ctx.settings, getattr(context.bot, "username", "") or "", u.id))
    elif action == "features":
        await show(FEATURES_TEXT, _back())
    elif action == "groups":
        await show(GROUPS_TEXT, _back())
    elif action == "about":
        await show(html.escape(ABOUT_TEXT), _back())
    elif action == "mem":
        await show(await _memories_screen(ctx, u.id), _back())
    elif action == "settings":
        ctx.user_state.pop(u.id, None)
        await show(*await _settings_screen(ctx, u.id))
    elif action == "lang" and arg in VALID_LANGUAGES:
        await ctx.users.get_or_create(u.id)
        await ctx.users.set_language(u.id, arg)
        await show(*await _settings_screen(ctx, u.id))
    elif action == "gender" and arg in ("male", "female"):
        await ctx.users.get_or_create(u.id)
        await ctx.users.set_gender(u.id, arg)
        await show(*await _settings_screen(ctx, u.id))
    elif action == "name":
        ctx.user_state[u.id] = "name"
        await show("✏️ Kis naam se bulau? Bas naam type karke bhej do 😊", _back("st:settings"))
    elif action == "link":
        if not ctx.settings.api_enabled:
            await show("🌐 Web chat abhi band hai.", _back())
        else:
            await ctx.users.get_or_create(u.id, getattr(u, "first_name", "") or "", getattr(u, "username", "") or "")
            code = await ctx.web_auth.create_link_code(u.id)
            mins = ctx.settings.api_link_code_ttl_seconds // 60
            await show(f"🌐 <b>Web chat code:</b> <code>{code}</code>\n{mins} minute mein use karo, ek hi baar chalega. "
                       "Kisi ko share mat karna!\nWeb par same chat aur yaadein milengi.", _back())
    elif action == "games":
        kb = InlineKeyboardMarkup([
            [Btn(GAMES["truth"][0], callback_data="st:g:truth"), Btn(GAMES["dare"][0], callback_data="st:g:dare")],
            [Btn(GAMES["wyr"][0], callback_data="st:g:wyr"), Btn(GAMES["quote"][0], callback_data="st:g:quote")],
            [Btn("⬅️ Back", callback_data="st:home")],
        ])
        await show("🎮 <b>Games</b>\nKya khelna hai? 😄", kb)
    elif action == "g" and arg in GAMES:
        label, pool = GAMES[arg]
        kb = InlineKeyboardMarkup([[Btn("🔁 Aur ek", callback_data=f"st:g:{arg}"), Btn("🎮 Games", callback_data="st:games")],
                                   [Btn("⬅️ Home", callback_data="st:home")]])
        await show(f"{label}\n\n{random.choice(pool)}", kb)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.message, HELP_TEXT)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.message, ABOUT_TEXT)
