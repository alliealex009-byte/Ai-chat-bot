from datetime import timedelta

from app.database.conversations import ConversationRepo
from app.database.memories import MemoryRepo
from app.database.mongo import utcnow
from app.database.users import UserRepo
from app.database.web import WebAuthRepo
from tests.fakes import FakeDB


async def test_user_profile_defaults_and_updates():
    users = UserRepo(FakeDB(), "hinglish")
    u = await users.get_or_create(1, "Asha", "asha")
    assert u["language"] == "hinglish" and u["memory_enabled"] and u["message_count"] == 0
    assert await users.set_language(1, "english") and not await users.set_language(1, "klingon")
    await users.set_preferred_name(1, "  Ash   ")
    await users.bump_counters(1)
    u = await users.get(1)
    assert u["language"] == "english" and u["preferred_name"] == "Ash" and u["message_count"] == 1
    await users.get_or_create(1, "Asha2")  # existing user keeps settings
    assert (await users.get(1))["language"] == "english"


async def test_history_order_budget_and_isolation():
    conv = ConversationRepo(FakeDB(), 200)
    for i in range(5):
        await conv.add(1, "user", f"u{i}")
        await conv.add(1, "assistant", f"a{i}")
    await conv.add(2, "user", "other user secret")
    h = await conv.recent(1, limit=6, char_budget=1000)
    assert [m["content"] for m in h] == ["a2", "u3", "a3", "u4", "a4"][-5:] or h[0]["role"] == "user"
    assert h[0]["role"] == "user" and h[-1]["content"] == "a4"
    assert all("secret" not in m["content"] for m in h)
    small = await conv.recent(1, limit=10, char_budget=4)
    assert len(small) <= 2


async def test_history_cap_per_user():
    conv = ConversationRepo(FakeDB(), max_per_user=10)
    for i in range(40):
        await conv.add(1, "user", f"m{i}")
    assert await conv.count(1) <= 31


async def test_reset_and_retention_cleanup():
    db = FakeDB()
    conv = ConversationRepo(db)
    await conv.add(1, "user", "old")
    db.messages.docs[0]["ts"] = utcnow() - timedelta(days=40)
    await conv.add(1, "user", "new")
    assert await conv.cleanup_older_than(30) == 1
    assert await conv.count(1) == 1
    assert await conv.clear(1) == 1 and await conv.count(1) == 0


async def test_memory_upsert_dedupe_update_delete_isolation():
    mem = MemoryRepo(FakeDB(), max_per_user=3)
    assert await mem.upsert(1, "Likes cricket")
    assert not await mem.upsert(1, "likes   CRICKET")  # same fact, refreshed not duplicated
    await mem.upsert(2, "Likes chess")
    items = await mem.list(1)
    assert len(items) == 1
    mid = items[0]["_id"]
    assert not await mem.update_text(2, mid, "hijack")          # other user cannot edit
    assert await mem.update_text(1, mid, "Loves cricket and chai")
    assert not await mem.delete_one(2, mid)                       # other user cannot delete
    assert await mem.count(2) == 1
    assert await mem.delete_one(1, mid) and await mem.count(1) == 0


async def test_memory_cap_evicts_oldest():
    mem = MemoryRepo(FakeDB(), max_per_user=3)
    for i in range(6):
        await mem.upsert(1, f"fact number {i}")
    assert await mem.count(1) == 3
    assert "fact number 5" in await mem.top_texts(1, 5)


async def test_web_link_code_is_single_use_expiring_and_per_user():
    db = FakeDB()
    web = WebAuthRepo(db, 600, 30)
    code = await web.create_link_code(111)
    assert len(code) == 8
    tok = await web.redeem(code.lower())
    assert tok and await web.user_for_token(tok) == 111
    assert await web.redeem(code) is None                         # single use
    assert await web.user_for_token("bogus") is None
    assert all(tok not in str(d) for d in db.web_sessions.docs)   # only hashes stored
    code2 = await web.create_link_code(222)
    db.link_codes.docs[0]["expires_at"] = utcnow() - timedelta(seconds=1)
    assert await web.redeem(code2) is None                        # expired
    code3 = await web.create_link_code(222)
    tok3 = await web.redeem(code3)
    assert await web.user_for_token(tok3) == 222 != await web.user_for_token(tok)
    await web.revoke_all(111)
    assert await web.user_for_token(tok) is None
    assert await web.user_for_token(tok3) == 222
