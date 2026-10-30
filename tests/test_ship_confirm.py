"""Покупка корабля — только после подтверждения отдельной кнопкой."""

from __future__ import annotations

import pytest

from app.errors import StaleAction
from tests.conftest import make_user, snapshot
from tests.test_handlers import Harness

STALE = ("⏳ Действие устарело, откройте меню снова", True)


async def _pilot(game, uid: int = 1) -> None:
    await make_user(game, uid, balance=20_000)
    async with game.db.transaction() as conn:
        await conn.execute("UPDATE users SET xp = 900, level = 10 WHERE user_id = ?", (uid,))


async def test_command_asks_for_confirmation(game):
    await _pilot(game)
    h = Harness(game)
    before = await snapshot(game, 1)
    await h.send(1, "/shipyard corvette")
    assert "Купить «<b>Корвет</b>» за <b>10000</b>" in h.bot.texts()[-1]
    assert await snapshot(game, 1) == before
    await h.press(1, h.button("✅ Купить за 10000"))
    p = await game.accounts.profile(1)
    assert p.ship.ship_class == "corvette" and p.balance == 10_000


async def test_shipyard_menu_flow_and_double_press(game):
    await _pilot(game)
    h = Harness(game)
    await h.send(1, "/shipyard")
    await h.press(1, h.button("Купить «Разведчик»"))  # выбор ничего не списывает
    assert (await game.accounts.profile(1)).balance == 20_000
    confirm = h.button("✅ Купить за 2500")
    await h.press(1, confirm)
    await h.press(1, confirm)
    assert h.bot.answers()[-1] == STALE
    p = await game.accounts.profile(1)
    assert p.ship.ship_class == "scout" and p.balance == 17_500


async def test_cancel_and_foreign_user(game):
    await _pilot(game)
    await make_user(game, 2)
    h = Harness(game)
    await h.send(1, "/shipyard")
    choose = h.button("Купить «Грузовик»")
    await h.press(2, choose)
    assert h.bot.answers()[-1] == ("⛔ Эта кнопка не для вас", True)
    await h.press(1, choose)
    before = await snapshot(game, 1)
    await h.press(1, h.button("Отмена"))
    assert "отменена" in h.bot.texts()[-1]
    assert await snapshot(game, 1) == before


async def test_token_bound_to_confirmed_ship(game):
    await _pilot(game)
    token = await game.tokens.issue(1, None, "shipyard", {"ship": "scout"})
    with pytest.raises(StaleAction):
        await game.ships.buy_ship(1, "corvette", token=token)


async def test_unsellable_ship_rejected_before_confirmation(game):
    await _pilot(game)
    h = Harness(game)
    await h.send(1, "/shipyard shuttle")
    assert "нельзя купить" in h.bot.texts()[-1]
    await h.send(1, "/shipyard ufo")
    assert "Неизвестный класс" in h.bot.texts()[-1]
