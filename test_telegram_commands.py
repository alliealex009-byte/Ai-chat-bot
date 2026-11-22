"""Telegram command handler tests with fake Update/Context objects (need python-telegram-bot; skipped otherwise)."""
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram")

from app.tg import chat, commands, media, start  # noqa: E402


class Msg:
    def __init__(self, text="", **kw):
        self.text, self.replies, self.chat_id = text, [], 1
        self.message_id, self.reply_to_message, self.reply_kwargs = 77, kw.get("reply_to_message"), []
        self.sticker = kw.get("sticker"); self.photo = kw.get("photo"); self.voice = kw.get("voice")
        self.audio = self.video_note = None

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        self.reply_kwargs.append(kw)


def _upd(uid, msg, uid_update=1, data=None):
    q = None
    if data is not None:
        q = SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, edits=[])
        async def answer(): pass
        async def edit(text, reply_markup=None): q.edits.append(text)
        q.answer, q.edit_message_text = answer, edit
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid, first_name="Asha", username="a", is_bot=False),
                           effective_chat=SimpleNamespace(id=uid, type="private", title=""), message=msg,
                           update_id=uid_update, callback_query=q)


def _ctx(stack, args=None):
    bot = SimpleNamespace()
    async def act(**k): pass
    bot.send_chat_action = act
    return SimpleNamespace(application=SimpleNamespace(bot_data={"ctx": stack.ctx}), args=args or [], bot=bot)


async def test_start_help_about_are_honest_and_hinglish(stack):
    m = Msg(); await start.start(_upd(1, m), _ctx(stack))
    assert "Ria" in m.replies[0] and "AI" not in m.replies[0]
    m = Msg(); await start.help_cmd(_upd(1, m), _ctx(stack))
    for cmd in ("/start", "/help", "/reset", "/memory", "/forget", "/language", "/settings", "/about"):
        assert cmd in m.replies[0]
    m = Msg(); await start.about(_upd(1, m), _ctx(stack))
    assert "Ria" in m.replies[0] and "AI chat companion" in m.replies[0] and "insaan nahi" in m.replies[0]
    assert "Gemma" not in m.replies[0]


async def test_memory_list_delete_edit_add(stack):
    await stack.ctx.memories.upsert(1, "Likes cricket"); await stack.ctx.memories.upsert(2, "Other user's fact")
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack))
    assert "Likes cricket" in m.replies[0] and "Other user" not in m.replies[0]
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack, ["edit", "1", "Loves", "chai"]))
    assert (await stack.ctx.memories.top_texts(1, 5)) == ["Loves chai"]
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack, ["add", "my", "password", "is", "abc"]))
    assert "yaad nahi rakhungi" in m.replies[0]
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack, ["delete", "1"]))
    assert await stack.ctx.memories.count(1) == 0 and await stack.ctx.memories.count(2) == 1
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack))
    assert "kuch khaas yaad nahi" in m.replies[0]


async def test_forget_requires_confirmation_then_deletes_only_caller(stack):
    stack.queue.start()
    await stack.engine.chat(1, "hello", "telegram"); await stack.engine.chat(2, "hello", "telegram")
    await stack.ctx.memories.upsert(1, "Likes tea")
    m = Msg(); await commands.forget(_upd(1, m), _ctx(stack))
    assert await stack.ctx.conversations.count(1) == 2          # nothing deleted yet
    u = _upd(1, None, data="forget:no"); await commands.on_callback(u, _ctx(stack))
    assert await stack.ctx.conversations.count(1) == 2
    u = _upd(1, None, data="forget:yes"); await commands.on_callback(u, _ctx(stack))
    assert await stack.ctx.conversations.count(1) == 0 and await stack.ctx.memories.count(1) == 0
    assert await stack.ctx.users.get(1) is None and await stack.ctx.conversations.count(2) == 2
    await stack.queue.shutdown(1)


async def test_reset_language_settings_name_link(stack):
    stack.queue.start()
    await stack.engine.chat(1, "hello", "telegram")
    m = Msg(); await commands.reset(_upd(1, m), _ctx(stack))
    assert await stack.ctx.conversations.count(1) == 0
    await commands.on_callback(_upd(1, None, data="lang:english"), _ctx(stack))
    assert (await stack.ctx.users.get(1))["language"] == "english"
    await commands.on_callback(_upd(1, None, data="mem:off"), _ctx(stack))
    assert (await stack.ctx.users.get(1))["memory_enabled"] is False
    m = Msg(); await commands.settings(_upd(1, m), _ctx(stack))
    assert "Memory: OFF" in m.replies[0] and "English" in m.replies[0]
    m = Msg(); await commands.name(_upd(1, m), _ctx(stack, ["Rahul"]))
    assert (await stack.ctx.users.get(1))["preferred_name"] == "Rahul"
    m = Msg(); await commands.link(_upd(1, m), _ctx(stack))
    code = m.replies[0].split(": ")[1].split("\n")[0]
    assert await stack.ctx.web_auth.redeem(code)
    await stack.queue.shutdown(1)


async def test_health_command_is_admin_only(stack):
    class M:  # health needs mongo ping
        async def ping(self): return True
    stack.ctx.mongo = M()
    m = Msg(); await commands.health(_upd(777, m), _ctx(stack))
    assert m.replies == []
    stack.settings.admin_user_ids.append(777)
    m = Msg(); await commands.health(_upd(777, m), _ctx(stack))
    assert "status:" in m.replies[0] and "ollama" in m.replies[0]


async def test_text_message_flow_dedupe_and_rate_limit(stack):
    stack.queue.start()
    stack.settings.__dict__["user_rate_limit_messages"] = 2
    from app.services.limiter import SlidingWindowLimiter
    stack.ctx.user_limiter = SlidingWindowLimiter(2, 60)
    m = Msg("Hi"); await chat.on_text(_upd(1, m, uid_update=10), _ctx(stack))
    assert m.replies == ["Hieee! 💗"]
    dup = Msg("Hi"); await chat.on_text(_upd(1, dup, uid_update=10), _ctx(stack))   # same update_id
    assert dup.replies == []
    for i in range(3):
        await chat.on_text(_upd(1, Msg("x"), uid_update=20 + i), _ctx(stack))
    assert stack.engine.stats["messages"] == 2        # 3rd+ messages were rate-limited before reaching the AI
    await stack.queue.shutdown(1)


async def test_long_reply_is_split(stack):
    stack.queue.start()
    stack.local.script = ["word " * 2500]
    m = Msg("explain everything please about space"); await chat.on_text(_upd(1, m, uid_update=5), _ctx(stack))
    assert len(m.replies) >= 3 and all(len(r) <= 4096 for r in m.replies)
    await stack.queue.shutdown(1)


async def test_unsupported_media_gets_natural_explanation(stack):
    for kw, needle in (({"sticker": object()}, "sticker"), ({"photo": [1]}, "images"), ({"voice": object()}, "Voice")):
        m = Msg(**kw); await media.on_media(_upd(1, m, uid_update=hash(needle) % 10000), _ctx(stack))
        assert m.replies and needle.lower() in m.replies[0].lower()


# ---------------------------------------------------------------- groups
def _gupd(uid, msg, update_id, chat_id=-1001, ctype="supergroup"):
    u = _upd(uid, msg, update_id)
    u.effective_chat = SimpleNamespace(id=chat_id, type=ctype, title="Friends")
    u.effective_user.is_bot = False
    return u


def _gctx(stack):
    c = _ctx(stack)
    c.bot = SimpleNamespace(username="ria_bot", id=999, send_chat_action=c.bot.send_chat_action)
    return c


async def test_group_ignores_chatter_but_answers_name_tag_and_reply(stack):
    stack.queue.start()
    m = Msg("hello everyone kya scene"); await chat.on_text(_gupd(1, m, 1), _gctx(stack))
    assert m.replies == [] and not stack.local.calls
    m = Msg("Ria kya kar rahi ho"); await chat.on_text(_gupd(1, m, 2), _gctx(stack))
    assert m.replies == ["Hieee! 💗"] and "reply_parameters" in m.reply_kwargs[0]     # sent as a reply to the message
    m = Msg("@ria_bot hi"); await chat.on_text(_gupd(2, m, 3), _gctx(stack))
    assert m.replies
    rb = SimpleNamespace(from_user=SimpleNamespace(id=999))
    m = Msg("haan sahi", reply_to_message=rb); await chat.on_text(_gupd(3, m, 4), _gctx(stack))
    assert m.replies
    assert (await stack.ctx.chats.get(-1001))["title"] == "Friends"                   # group is tracked
    await stack.queue.shutdown(1)


async def test_group_respects_owner_switches_ban_and_per_group_toggle(stack):
    stack.queue.start()
    await stack.ctx.runtime.set("group_enabled", False)
    stack.ctx.runtime.ttl = 0
    m = Msg("ria hi"); await chat.on_text(_gupd(1, m, 10), _gctx(stack)); assert m.replies == []
    await stack.ctx.runtime.set("group_enabled", True)
    stack.ctx.banned.add(5)
    m = Msg("ria hi"); await chat.on_text(_gupd(5, m, 11), _gctx(stack)); assert m.replies == []
    await stack.ctx.chats.touch(-1001, "supergroup", "Friends"); await stack.ctx.chats.set_enabled(-1001, False)
    m = Msg("ria hi"); await chat.on_text(_gupd(1, m, 12), _gctx(stack)); assert m.replies == []
    await stack.queue.shutdown(1)


async def test_dm_paused_when_bot_disabled_and_stickers_follow_replies(stack):
    stack.queue.start()
    stack.ctx.runtime.ttl = 0
    await stack.ctx.stickers.add("u1", "file1", "💗", "packA")
    await stack.ctx.runtime.set("sticker_chance", 50)
    sent = []

    async def send_sticker(**kw): sent.append(kw)
    c = _ctx(stack); c.bot.send_sticker = send_sticker
    import random; random.seed(1)
    for i in range(12):
        await chat.on_text(_upd(1, Msg("hi"), 100 + i), c)
        stack.ctx.user_limiter._events.clear()
    assert sent and all(k["sticker"] == "file1" for k in sent) and len(sent) < 12     # sometimes, not every time
    await stack.ctx.runtime.set("bot_enabled", False)
    m = Msg("hi"); await chat.on_text(_upd(1, m, 500), c)
    assert "break" in m.replies[0]
    await stack.queue.shutdown(1)


# ---------------------------------------------------------------- owner panel
async def test_owner_panel_is_owner_only(stack):
    from app.tg import owner
    stack.settings.admin_user_ids.append(42)
    m = Msg(); await owner.panel(_upd(1000, m), _ctx(stack)); assert m.replies == []          # stranger: ignored
    m = Msg(); await owner.panel(_upd(42, m), _ctx(stack))
    assert "Ria owner panel" in m.replies[0] and "AAKASH" in m.replies[0] and "Advik_prakashh" in m.replies[0]
    u = _upd(1000, None, data="own:ctl")
    answers = []
    async def ans(text=None, show_alert=False): answers.append(text)
    u.callback_query.answer = ans
    await owner.owner_callback(u, _ctx(stack))
    assert answers == ["Not allowed"] and not u.callback_query.edits                            # stranger's button press rejected


async def test_owner_controls_toggle_and_ban_flow(stack):
    from telegram.ext import ApplicationHandlerStop
    from app.tg import owner
    stack.settings.admin_user_ids.append(42)
    stack.ctx.runtime.ttl = 0
    u = _upd(42, None, data="own:tg:stickers_enabled"); await owner.owner_callback(u, _ctx(stack))
    assert (await stack.ctx.runtime.all())["stickers_enabled"] is False and "Stickers: OFF" in u.callback_query.edits[0]
    u = _upd(42, None, data="own:ban"); await owner.owner_callback(u, _ctx(stack))
    assert stack.ctx.owner_state[42]["action"] == "ban_who"
    await stack.ctx.users.get_or_create(900, "Bad", "baduser")
    with pytest.raises(ApplicationHandlerStop):
        await owner.owner_input(_upd(42, Msg("@baduser")), _ctx(stack))
    assert 900 in stack.ctx.banned
    stack.ctx.owner_state[42] = {"action": "ban_who"}
    with pytest.raises(ApplicationHandlerStop):
        await owner.owner_input(_upd(42, Msg("42")), _ctx(stack))                                 # owners can't be banned
    assert 42 not in stack.ctx.banned


async def test_owner_broadcast_flow_sends_to_dm_users_only(stack):
    from telegram.ext import ApplicationHandlerStop
    from app.tg import owner
    import asyncio
    stack.settings.admin_user_ids.append(42)
    for uid in (1, 2):
        await stack.ctx.users.get_or_create(uid, "n", f"u{uid}")
    await stack.ctx.chats.touch(-55, "supergroup", "G")
    sent = []
    async def send_message(cid, text, **kw): sent.append((cid, text))
    c = _ctx(stack); c.bot.send_message = send_message
    await owner.owner_callback(_upd(42, None, data="own:bct:dm"), c)
    with pytest.raises(ApplicationHandlerStop):
        await owner.owner_input(_upd(42, Msg("Namaste sabko!")), c)
    assert stack.ctx.owner_state[42]["action"] == "bc_confirm"
    u = _upd(42, None, data="own:bcgo"); u.callback_query.message = SimpleNamespace(chat_id=42)
    await owner.owner_callback(u, c)
    await asyncio.gather(*stack.ctx.owner_tasks)
    assert sorted(cid for cid, t in sent if t == "Namaste sabko!") == [1, 2]                      # groups excluded for 'dm' target
    assert any("Broadcast done" in t for cid, t in sent if cid == 42)


async def test_owner_sticker_manager_add_and_remove_pack(stack):
    from telegram.ext import ApplicationHandlerStop
    from app.tg import owner
    stack.settings.admin_user_ids.append(42)
    pack = SimpleNamespace(name="CutePack", stickers=[
        SimpleNamespace(file_unique_id=f"u{i}", file_id=f"f{i}", emoji="😂") for i in range(3)])
    async def get_sticker_set(name): return pack
    c = _ctx(stack); c.bot.get_sticker_set = get_sticker_set
    await owner.owner_callback(_upd(42, None, data="own:st:addpack"), c)
    sticker = SimpleNamespace(file_unique_id="u0", file_id="f0", emoji="😂", set_name="CutePack")
    m = Msg(); m.sticker = sticker; m.text = None
    with pytest.raises(ApplicationHandlerStop):
        await owner.owner_input(_upd(42, m), c)
    assert await stack.ctx.stickers.count() == 3
    await owner.owner_callback(_upd(42, None, data="own:st:rmpack"), c)
    with pytest.raises(ApplicationHandlerStop):
        await owner.owner_input(_upd(42, m), c)
    assert await stack.ctx.stickers.count() == 0
