import json
from datetime import timedelta

from app.database.mongo import utcnow
from app.services import dataset, nudges


class Bot:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    async def send_message(self, chat_id, text):
        if self.fail:
            raise self.fail
        self.sent.append((chat_id, text))


async def _old_user(stack, uid, hours=60):
    await stack.ctx.users.get_or_create(uid, "Rahul")
    stack.db.users.docs[-1]["last_seen"] = utcnow() - timedelta(hours=hours)
    stack.db.users.docs[-1]["nudges_sent"] = 0


async def test_nudges_only_for_inactive_users_and_respect_limits(stack):
    await _old_user(stack, 1); await stack.ctx.users.get_or_create(2, "Fresh")
    bot = Bot()
    assert await nudges.run_once(stack.ctx, bot) == 1 and bot.sent[0][0] == 1 and "Rahul" in bot.sent[0][1] + "Rahul"
    assert await nudges.run_once(stack.ctx, bot) == 0                  # 72h gap
    await stack.ctx.runtime.set("nudges_enabled", False); stack.ctx.runtime.ttl = 0
    stack.db.users.docs[0]["last_nudge"] = utcnow() - timedelta(days=5)
    assert await nudges.run_once(stack.ctx, bot) == 0                  # owner switch


async def test_nudge_blocked_user_is_marked_and_not_retried(stack):
    class Forbidden(Exception): pass
    await _old_user(stack, 1)
    assert await nudges.run_once(stack.ctx, Bot(Forbidden())) == 0
    assert (await stack.ctx.users.get(1))["blocked"] is True
    assert await nudges.run_once(stack.ctx, Bot()) == 0


async def test_dataset_export_is_pseudonymous_private_only_and_drops_sensitive(stack, tmp_path):
    c = stack.ctx.conversations
    await c.add(1, "user", "mujhe cricket pasand hai"); await c.add(1, "assistant", "arre waah 😄")
    await c.add(1, "user", "mera password hunter2"); await c.add(1, "assistant", "ok")
    await c.add(-100123, "user", "group message"); await c.add(10**13 + 5, "user", "third party chat")
    path = str(tmp_path / "d.jsonl")
    info = await dataset.build_dataset(stack.ctx, path)
    text = open(path, encoding="utf-8").read()
    rows = [json.loads(l) for l in text.splitlines()]
    assert info["users"] == 1 and len(rows) == 1
    assert "cricket" in text and "hunter2" not in text and "group message" not in text and "third party" not in text
    assert rows[0]["user"] != "1" and len(rows[0]["user"]) == 10


async def test_keep_forever_default_never_deletes_old_chats():
    from tests.fakes import make_settings
    assert make_settings().conversation_retention_days == 0
