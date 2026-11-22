import asyncio

import pytest

from app.database.chats import ChatsRepo
from app.database.runtime import RuntimeSettings
from app.database.stickers import StickersRepo
from app.database.users import UserRepo
from app.services.broadcast import Blocked, FloodWait, broadcast
from app.services.triggers import should_respond_in_group, strip_mention
from tests.fakes import FakeDB


def test_group_trigger_on_name_tag_or_reply_only():
    f = lambda t, reply=False: should_respond_in_group(t, "ria_bot", reply)
    for yes in ("Ria kya kar rahi ho", "hey ria!", "RIA", "arre riaa sun", "@ria_bot hi", "kaisi ho ria?", "रिया सुनो"):
        assert f(yes), yes
    assert f("kuch bhi", reply=True)
    for no in ("hello everyone", "material hai", "Riana aayi thi", "variable set kar", "", "arrival at 5"):
        assert not f(no), no


def test_strip_mention():
    assert strip_mention("@Ria_Bot kya haal hai", "ria_bot") == "kya haal hai"


async def test_runtime_settings_defaults_toggle_cycle_and_persist():
    db = FakeDB()
    rt = RuntimeSettings(db, ttl=0)
    a = await rt.all()
    assert a["bot_enabled"] and a["stickers_enabled"] and a["sticker_chance"] == 15
    assert await rt.toggle("group_enabled") is False
    assert (await RuntimeSettings(db, ttl=0).all())["group_enabled"] is False     # persisted in DB
    seen = [await rt.cycle_chance() for _ in range(5)]
    assert seen == [30, 50, 0, 5, 15]
    with pytest.raises(KeyError):
        await rt.set("evil", 1)


async def test_sticker_library_add_pick_remove_pack():
    st = StickersRepo(FakeDB())
    assert await st.pick(["😂"]) is None
    assert await st.add("u1", "f1", "😂", "packA") and not await st.add("u1", "f1", "😂", "packA")
    await st.add_many([{"unique_id": "u2", "file_id": "f2", "emoji": "🥺", "set_name": "packA"},
                       {"unique_id": "u3", "file_id": "f3", "emoji": "😏", "set_name": "packB"}])
    assert await st.count() == 3 and await st.packs() == {"packA": 2, "packB": 1}
    assert (await st.pick(["🥺"]))["file_id"] == "f2"          # emoji match preferred
    assert (await st.pick(["🔥"])) is not None                   # no match -> any sticker
    assert await st.remove("u3") and not await st.remove("u3")
    assert await st.remove_pack("packA") == 2 and await st.count() == 0


async def test_chats_and_user_ban_helpers():
    db = FakeDB()
    chats, users = ChatsRepo(db), UserRepo(db)
    await chats.touch(-100, "supergroup", "Friends"); await chats.touch(5, "private", "x")
    assert await chats.group_ids() == [-100]
    await chats.set_enabled(-100, False)
    assert (await chats.get(-100))["enabled"] is False
    await chats.touch(-100, "supergroup", "Friends")             # touching again must not re-enable
    assert (await chats.get(-100))["enabled"] is False
    await chats.set_active(-100, False)
    assert await chats.count() == 0
    for uid in (1, 2, 3):
        await users.get_or_create(uid, "n", f"User{uid}")
    await users.set_banned(2, True); await users.set_blocked(3, True)
    assert await users.broadcast_ids() == [1] and await users.list_banned() == [2]
    assert (await users.find_by_username("@user1"))["_id"] == 1


async def test_broadcast_counts_blocked_floodwait_and_cancel():
    sent, blocked = [], []

    async def send(cid):
        if cid == 2:
            raise Blocked()
        if cid == 3 and 3 not in sent:
            sent.append(3)               # first attempt floods, retry succeeds
            raise FloodWait(0)
        if cid == 4:
            raise RuntimeError("boom")
        sent.append(cid)

    async def on_blocked(cid):
        blocked.append(cid)

    res = await broadcast([1, 2, 3, 4, 5], send, on_blocked, rate_per_sec=1000)
    assert res["sent"] == 3 and res["blocked"] == 1 and res["failed"] == 1 and blocked == [2] and not res["cancelled"]
    cancel = asyncio.Event(); cancel.set()
    res = await broadcast([1, 2], send, None, cancel, rate_per_sec=1000)
    assert res["cancelled"] and res["sent"] == 0
