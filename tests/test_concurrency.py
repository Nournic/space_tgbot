"""Конкурентные операции и перезапуск сервисов."""

import asyncio

from app.db.connection import Database
from app.errors import GameError
from app.services import build_game
from tests.conftest import SEED, give_items, make_user


async def test_parallel_buys_never_overdraw_or_overfill(game):
    await make_user(game, 1, balance=200)
    price = game.economy.prices_on("earth")["water"][0]
    results = await asyncio.gather(*(game.economy.buy(1, "water", 3) for _ in range(15)), return_exceptions=True)
    ok = sum(1 for r in results if not isinstance(r, Exception))
    assert all(isinstance(r, GameError) for r in results if isinstance(r, Exception))
    p = await game.accounts.profile(1)
    assert p.balance >= 0 and p.cargo_used <= p.ship.capacity
    assert p.balance == 200 - ok * 3 * price
    assert p.inventory.get("water", 0) == ok * 3


async def test_parallel_sells_never_negative(game):
    await make_user(game, 1)
    await give_items(game, 1, iron=10)
    results = await asyncio.gather(*(game.economy.sell(1, "iron", 3) for _ in range(6)), return_exceptions=True)
    ok = sum(1 for r in results if not isinstance(r, Exception))
    assert ok == 3
    assert (await game.accounts.profile(1)).inventory == {"iron": 1}


async def test_parallel_upgrades_respect_cost_and_max(game):
    await make_user(game, 1, balance=100_000)
    results = await asyncio.gather(*(game.ships.upgrade(1, "weapon") for _ in range(10)), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert sorted(r.new_level for r in ok) == [1, 2, 3, 4, 5]
    p = await game.accounts.profile(1)
    assert p.ship.weapon_level == 5 and p.balance == 100_000 - 7_500


async def test_concurrent_pvp_accept_pays_once(game):
    await make_user(game, 1)
    await make_user(game, 2)
    c = await game.pvp.create(1, 2, 100, None)
    results = await asyncio.gather(*(game.pvp.accept(c.id, 2) for _ in range(6)), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1
    total = (await game.accounts.profile(1)).balance + (await game.accounts.profile(2)).balance
    assert total == 2000


async def test_concurrent_cancel_and_expire_refund_once(game, clock):
    await make_user(game, 1)
    await make_user(game, 2)
    c = await game.pvp.create(1, 2, 400, None)
    clock.advance(301)
    await asyncio.gather(
        game.pvp.cancel(c.id, 1), game.pvp.expire_due(), game.pvp.decline(c.id, 2), return_exceptions=True
    )
    assert (await game.accounts.profile(1)).balance == 1000


async def test_restart_keeps_state(game, clock, rng, db_path):
    await make_user(game, 1)
    await make_user(game, 2)
    await give_items(game, 1, water=5)
    offer = await game.offers.create(1, 2, "water", 2, 10, None)
    duel = await game.pvp.create(1, 2, 150, None)
    await game.travel.travel(1, "mars")
    await game.quests.today(1)
    # «Перезапуск»: новые объекты БД и сервисов поверх того же файла.
    db2 = Database(db_path)
    await db2.init()
    g2 = build_game(db2, seed=SEED, clock=clock, rng=rng)
    p = await g2.accounts.profile(1)
    assert p.planet_id == "mars" and p.balance == 850 and p.ship.energy == 90
    assert p.reserved == {"water": 2}
    _, quests = await g2.quests.today(1)
    assert next(q for q in quests if q.quest_id == "daily_travel").progress == 1
    assert (await g2.offers.get(offer.id)).status == "pending"
    clock.advance(400)
    notices = await g2.cleanup()  # как при старте бота
    assert {n.kind for n in notices} == {"offer", "challenge"}
    assert (await g2.accounts.profile(1)).balance == 1000
    assert (await g2.pvp.get(duel.id)).status == "expired"
