"""/admin: статистика только для ADMIN_IDS и только в личке."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from aiogram.types import Chat, Message, Update

from config import parse_admin_ids
from tests.conftest import give_items, make_user
from tests.test_handlers import Harness, user

ADMIN = 7


class AdminHarness(Harness):
    async def say(self, uid: int, text: str, private: bool) -> None:
        self.update_id += 1
        chat = Chat(id=uid, type="private") if private else Chat(id=-1001, type="supergroup", title="Test")
        msg = Message(message_id=self.update_id, date=datetime.now(UTC), chat=chat, from_user=user(uid), text=text)
        await self.dp.feed_update(
            self.bot, Update(update_id=self.update_id, message=msg), game=self.game, admin_ids=frozenset({ADMIN})
        )


def test_parse_admin_ids():
    assert parse_admin_ids(None) == frozenset()
    assert parse_admin_ids("1, 2 3") == frozenset({1, 2, 3})
    with pytest.raises(RuntimeError):
        parse_admin_ids("1,abc")


async def test_stats_values(game, clock):
    await make_user(game, 1)
    await make_user(game, 2)
    await give_items(game, 1, water=4)
    await game.economy.sell(1, "water", 4)  # доход
    await game.pvp.create(1, 2, 100, None)  # ставка в escrow
    s = await game.admin.stats()
    assert (s.players, s.new_24h, s.active_24h) == (2, 2, 2)
    assert s.escrow == 100 and s.pending_duels == 1 and s.pending_offers == 0
    assert s.balances + s.escrow + s.treasuries == 2000 + s.income_24h
    assert s.income_24h > 0 and s.spent_24h == 100
    clock.advance(2 * 86_400)
    later = await game.admin.stats()
    assert (later.new_24h, later.active_24h, later.income_24h) == (0, 0, 0)


async def test_admin_command_access(game):
    h = AdminHarness(game)
    await h.say(1, "/admin", private=True)  # не админ — молчание
    assert h.bot.texts() == []
    await h.say(ADMIN, "/admin", private=False)
    assert "только в личке" in h.bot.texts()[-1]
    await h.say(ADMIN, "/admin", private=True)
    assert "Статистика сервера" in h.bot.texts()[-1]


async def test_admin_ignored_without_config(game):
    h = Harness(game)  # dp без admin_ids
    await h.send(ADMIN, "/admin")
    assert h.bot.texts() == []
