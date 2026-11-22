"""Telegram command handler tests with fake Update/Context objects (need python-telegram-bot; skipped otherwise)."""
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram")

from app.tg import chat, commands, media, start  # noqa: E402


class Msg:
    def __init__(self, text="", **kw):
        self.text, self.replies, self.chat_id = text, [], 1
        self.sticker = kw.get("sticker"); self.photo = kw.get("photo"); self.voice = kw.get("voice")
        self.audio = self.video_note = None

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def _upd(uid, msg, uid_update=1, data=None):
    q = None
    if data is not None:
        q = SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, edits=[])
        async def answer(): pass
        async def edit(text, reply_markup=None): q.edits.append(text)
        q.answer, q.edit_message_text = answer, edit
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid, first_name="Asha", username="a"), message=msg,
                           update_id=uid_update, callback_query=q)


def _ctx(stack, args=None):
    bot = SimpleNamespace()
    async def act(**k): pass
    bot.send_chat_action = act
    return SimpleNamespace(application=SimpleNamespace(bot_data={"ctx": stack.ctx}), args=args or [], bot=bot)


async def test_start_help_about_are_honest_and_hinglish(stack):
    m = Msg(); await start.start(_upd(1, m), _ctx(stack))
    assert "RIA" in m.replies[0]
    m = Msg(); await start.help_cmd(_upd(1, m), _ctx(stack))
    for cmd in ("/start", "/help", "/reset", "/memory", "/forget", "/language", "/settings", "/about"):
        assert cmd in m.replies[0]
    m = Msg(); await start.about(_upd(1, m), _ctx(stack))
    assert "AI" in m.replies[0] and "Gemma 3 4B" in m.replies[0] and "asli insaan nahi" in m.replies[0]


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
