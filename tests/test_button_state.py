"""Кнопка срабатывает только для того состояния, которое было на ней показано."""

from __future__ import annotations

import pytest

from app.errors import StaleAction
from tests.conftest import make_user, set_ship, snapshot
from tests.test_handlers import Harness


async def test_upgrade_button_stale_after_level_changed(game):
    await make_user(game, 1, balance=10_000)
    h = Harness(game)
    await h.send(1, "/upgrade")
    engine_button = h.button("Двигатель → 1")
    await game.ships.upgrade(1, "engine")  # улучшили командой, старая кнопка показывает цену уровня 1
    before = await snapshot(game, 1)
    await h.press(1, engine_button)
    assert h.bot.answers()[-1] == ("⏳ Действие устарело, откройте меню снова", True)
    assert await snapshot(game, 1) == before


async def test_upgrade_button_other_module_still_works(game):
    await make_user(game, 1, balance=10_000)
    h = Harness(game)
    await h.send(1, "/upgrade")
    weapon_button = h.button("Оружие → 1")
    await game.ships.upgrade(1, "engine")
    await h.press(1, weapon_button)
    assert (await game.accounts.profile(1)).ship.weapon_level == 1


async def test_repair_token_bound_to_damage(game):
    await make_user(game, 1)
    await set_ship(game, 1, hp=90)
    token = await game.tokens.issue(1, None, "repair", {"missing": 10})
    await set_ship(game, 1, hp=50)  # новые повреждения — цена уже не та, что на кнопке
    before = await snapshot(game, 1)
    with pytest.raises(StaleAction):
        await game.ships.repair(1, None, token=token)
    assert await snapshot(game, 1) == before


async def test_repair_button_flow(game):
    await make_user(game, 1)
    await set_ship(game, 1, hp=90)
    h = Harness(game)
    await h.send(1, "/repair")
    await h.press(1, h.button("Полный ремонт за 50"))
    p = await game.accounts.profile(1)
    assert p.ship.hp == p.ship.max_hp and p.balance == 950


async def test_market_card_from_previous_day_is_stale(game, clock):
    await make_user(game, 1)
    clock.advance(12 * 3600 - 60)  # 23:59 UTC
    h = Harness(game)
    await h.send(1, "/market")
    await h.press(1, h.button("Вода"))
    buy = h.button("Купить 1")
    clock.advance(120)  # 00:01 — новые сутки, цены другие, а токен ещё жив
    before = await snapshot(game, 1)
    await h.press(1, buy)
    assert h.bot.answers()[-1] == ("⏳ Действие устарело, откройте меню снова", True)
    assert await snapshot(game, 1) == before
