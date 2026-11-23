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
        async def edit(text, reply_markup=None, **kw): q.edits.append(text)
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
    assert "Ria" in m.replies[0] and "AI" not in m.replies[0] and m.reply_kwargs[0]["parse_mode"] == "HTML"
    assert "<blockquote>" in m.replies[0] and "Streak" in m.replies[0]
    m = Msg(); await start.help_cmd(_upd(1, m), _ctx(stack))
    assert "/start" in m.replies[0] and "/forget" not in m.replies[0]
    m = Msg(); await start.about(_upd(1, m), _ctx(stack))
    assert "AI chat companion" in m.replies[0] and "insaan nahi" in m.replies[0] and "Privacy" in m.replies[0]
    assert "Gemma" not in m.replies[0]


async def test_memory_command_is_read_only_and_isolated(stack):
    await stack.ctx.memories.upsert(1, "Likes cricket"); await stack.ctx.memories.upsert(2, "Other user's fact")
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack))
    assert "Likes cricket" in m.replies[0] and "Other user" not in m.replies[0]
    m = Msg(); await commands.memory(_upd(1, m), _ctx(stack, ["delete", "1"]))      # no delete any more
    assert await stack.ctx.memories.count(1) == 1


def test_users_cannot_delete_data_or_switch_memory_off_from_the_bot():
    import inspect
    assert not hasattr(commands, "forget") and not hasattr(commands, "reset")
    src = inspect.getsource(commands) + inspect.getsource(start)
    assert "forget:" not in src and "mem:off" not in src and "/forget" not in src


async def test_menu_buttons_cover_settings_games_memories_link(stack):
    await stack.ctx.users.get_or_create(1, "Asha")
    await stack.ctx.memories.upsert(1, "Likes chai")
    async def press(data):
        u = _upd(1, None, data=data); await start.start_callback(u, _ctx(stack)); return u.callback_query.edits[-1]
    assert "Settings" in await press("st:settings")
    assert "English" in await press("st:lang:english") and (await stack.ctx.users.get(1))["language"] == "english"
    await press("st:gender:female"); assert (await stack.ctx.users.get(1))["gender"] == "female"
    assert "naam" in await press("st:name") and stack.ctx.user_state[1] == "name"
    assert "Likes chai" in await press("st:mem")
    assert "Games" in await press("st:games")
    assert "Truth" in await press("st:g:truth") and "Dare" in await press("st:g:dare")
    assert "Web chat code" in await press("st:link")
    assert "Privacy" in await press("st:about")
    assert "Hieee" in await press("st:home") and 1 not in stack.ctx.user_state


async def test_name_button_then_typing_sets_name(stack):
    stack.ctx.user_state[1] = "name"
    m = Msg("Rani")
    await chat.on_text(_upd(1, m), SimpleNamespace(application=SimpleNamespace(bot_data={"ctx": stack.ctx}), bot=SimpleNamespace(username="b", id=9)))
    assert (await stack.ctx.users.get(1))["preferred_name"] == "Rani" and "Rani" in m.replies[0]


async def test_language_name_gender_link_commands_still_work(stack):
    await commands.on_callback(_upd(1, None, data="lang:english"), _ctx(stack))
    assert (await stack.ctx.users.get(1))["language"] == "english"
    m = Msg(); await commands.settings(_upd(1, m), _ctx(stack))
    assert "English" in m.replies[0] and "Memory" not in m.replies[0]
    m = Msg(); await commands.name(_upd(1, m), _ctx(stack, ["Rahul"]))
    assert (await stack.ctx.users.get(1))["preferred_name"] == "Rahul"
    m = Msg(); await commands.link(_upd(1, m), _ctx(stack))
    code = m.replies[0].split(": ")[1].split("\n")[0]
    assert await stack.ctx.web_auth.redeem(code)


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


async def test_media_gets_natural_reactions(stack):
    from app.tg.media import STICKER
    m = Msg(sticker=SimpleNamespace(emoji="😂")); await media.on_media(_upd(1, m, uid_update=11), _ctx(stack))
    assert m.replies[0] in STICKER and "samajh nahi" not in m.replies[0]      # reacts like a person, no "can't read stickers"
    for kw, needle in (({"photo": [1]}, "images"), ({"voice": object()}, "Voice")):
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
    stack.settings.owner_user_ids.append(42)
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
    stack.settings.owner_user_ids.append(42)
    stack.ctx.runtime.ttl = 0
    u = _upd(42, None, data="own:tg:stickers_enabled"); await owner.owner_callback(u, _ctx(stack))
    assert (await stack.ctx.runtime.all())["stickers_enabled"] is False and "Controls" in u.callback_query.edits[0]
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
    stack.settings.owner_user_ids.append(42)
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
    stack.settings.owner_user_ids.append(42)
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


async def test_start_buttons_and_owner_button_visibility(stack):
    stack.settings.admin_user_ids.append(5)
    stack.settings.owner_user_ids.append(42)

    def labels(markup):
        return [b.text for row in markup.inline_keyboard for b in row]

    m = Msg(); await start.start(_upd(1, m), _ctx(stack))
    ls = labels(m.reply_kwargs[0]["reply_markup"])
    assert "🍀 Features" in ls and "👥 Groups" in ls and "💸 Promoter" in ls and "🎮 Games" in ls and "⚙️ Settings" in ls
    assert "👑 Owner panel" not in ls                                  # stranger
    m = Msg(); await start.start(_upd(5, m), _ctx(stack))
    assert "👑 Owner panel" not in labels(m.reply_kwargs[0]["reply_markup"])   # admin: no owner panel
    m = Msg(); await start.start(_upd(42, m), _ctx(stack))
    assert "👑 Owner panel" in labels(m.reply_kwargs[0]["reply_markup"])       # owner
    assert "Chats:" in m.replies[0] and "Yaadein:" in m.replies[0]


async def test_admin_cannot_open_owner_panel(stack):
    assert 5 not in stack.settings.owner_ids
    stack.settings.admin_user_ids.append(5)
    assert 5 not in stack.settings.owner_ids


async def test_start_callbacks_navigate(stack):
    u = _upd(1, None, data="st:features"); await start.start_callback(u, _ctx(stack))
    assert "Ria kya kya" in u.callback_query.edits[0]
    u = _upd(1, None, data="st:back"); await start.start_callback(u, _ctx(stack))
    assert "Chats:" in u.callback_query.edits[0]


# ---------------------------------------------------------------- secretary mode (Telegram Business)
class _BizBot:
    def __init__(self):
        self.sent, self.read = [], []

    async def send_message(self, **kw): self.sent.append(kw)
    async def send_chat_action(self, **kw): pass
    async def read_business_message(self, **kw): self.read.append(kw)


def _biz_update(sender_id, text, cid="c1", uid_update=1, chat_id=None):
    m = SimpleNamespace(text=text, business_connection_id=cid, chat=SimpleNamespace(id=chat_id or sender_id),
                        from_user=SimpleNamespace(id=sender_id, first_name="Riya", username="r", is_bot=False),
                        message_id=5)
    return SimpleNamespace(business_message=m, update_id=uid_update)


async def _run_biz(stack, upd, bot):
    from telegram.ext import ApplicationHandlerStop
    from app.tg import business
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data={"ctx": stack.ctx}), bot=bot)
    with pytest.raises(ApplicationHandlerStop):
        await business.on_business_message(upd, ctx)


async def test_secretary_introduces_then_answers_as_assistant_and_notifies_owner(stack):
    stack.queue.start()
    await stack.ctx.business.upsert("c1", 900, "AAKASH", True, True)
    bot = _BizBot()
    await _run_biz(stack, _biz_update(55, "Aakash kha ho", uid_update=1), bot)
    chat_msgs = [s for s in bot.sent if s["chat_id"] == 55]
    assert len(chat_msgs) == 1 and "Ria" in chat_msgs[0]["text"] and "Aakash" in chat_msgs[0]["text"]
    assert chat_msgs[0]["business_connection_id"] == "c1" and not stack.local.calls   # intro needs no model call
    assert any(s["chat_id"] == 900 and "Aakash kha ho" in s["text"] for s in bot.sent)   # owner notified
    await _run_biz(stack, _biz_update(55, "Tum aakash ho na", uid_update=2), bot)
    chat_msgs = [s for s in bot.sent if s["chat_id"] == 55]
    assert len(chat_msgs) == 2 and bot.read
    system = stack.local.calls[0][0]["content"]
    assert "AAKASH" in system.upper() and "NOT" in system and "assistant" in system
    await stack.queue.shutdown(1)


async def test_secretary_never_sends_error_texts_to_the_other_person(stack):
    from app.ai.errors import AIUnavailable
    stack.queue.start()
    await stack.ctx.business.upsert("c1", 900, "AAKASH", True, True)
    bot = _BizBot()
    await _run_biz(stack, _biz_update(55, "hi", uid_update=1), bot)           # intro
    stack.local.script = [AIUnavailable("down")] * 3
    before = len([s for s in bot.sent if s["chat_id"] == 55])
    await _run_biz(stack, _biz_update(55, "hello?", uid_update=2), bot)
    assert len([s for s in bot.sent if s["chat_id"] == 55]) == before         # silent on failure
    await stack.queue.shutdown(1)


async def test_secretary_respects_switches_owner_takeover_and_permissions(stack):
    stack.queue.start()
    stack.ctx.runtime.ttl = 0
    await stack.ctx.business.upsert("c1", 900, "AAKASH", True, True)
    bot = _BizBot()
    await _run_biz(stack, _biz_update(900, "main khud reply kar raha hu", uid_update=2, chat_id=55), bot)   # owner writes
    await _run_biz(stack, _biz_update(55, "hello", uid_update=3), bot)
    assert not [s for s in bot.sent if s["chat_id"] == 55]
    stack.ctx.secretary_pause.clear()
    await stack.ctx.runtime.set("secretary_enabled", False)
    await _run_biz(stack, _biz_update(55, "hi", uid_update=4), bot)
    assert not [s for s in bot.sent if s["chat_id"] == 55]
    await stack.ctx.runtime.set("secretary_enabled", True)
    await stack.ctx.business.upsert("c1", 900, "AAKASH", False, True)                          # no reply permission
    await _run_biz(stack, _biz_update(55, "hi", uid_update=5), bot)
    assert not [s for s in bot.sent if s["chat_id"] == 55]
    await stack.ctx.business.upsert("c1", 900, "AAKASH", True, False)                          # connection disabled
    await _run_biz(stack, _biz_update(55, "hi", uid_update=6), bot)
    assert not [s for s in bot.sent if s["chat_id"] == 55]
    await stack.queue.shutdown(1)
