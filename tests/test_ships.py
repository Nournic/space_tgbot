import pytest

from app.errors import GameError, InsufficientFunds, ValidationError
from tests.conftest import give_items, make_user, set_ship, snapshot


async def _set_xp(game, uid, xp):
    async with game.db.transaction() as conn:
        await conn.execute("UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (xp, 1 + xp // 100, uid))


async def test_upgrade_costs_and_max_level(game):
    await make_user(game, 1, balance=10_000)
    total = 0
    for n in range(1, 6):
        r = await game.ships.upgrade(1, "cargo")
        assert r.new_level == n and r.cost == 500 * n
        total += r.cost
    assert total == 7_500
    p = await game.accounts.profile(1)
    assert p.balance == 2_500 and p.ship.capacity == 70
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="максимального"):
        await game.ships.upgrade(1, "cargo")
    with pytest.raises(ValidationError):
        await game.ships.upgrade(1, "laser")
    assert await snapshot(game, 1) == before


async def test_upgrade_insufficient_funds(game):
    await make_user(game, 1, balance=499)
    with pytest.raises(InsufficientFunds):
        await game.ships.upgrade(1, "weapon")


async def test_armor_raises_max_hp_without_free_heal(game):
    await make_user(game, 1)
    await set_ship(game, 1, hp=60)
    await game.ships.upgrade(1, "armor")
    p = await game.accounts.profile(1)
    assert p.ship.max_hp == 125 and p.ship.hp == 60


async def test_buy_ship_rules(game):
    await make_user(game, 1, balance=20_000)
    with pytest.raises(GameError, match="уровень"):
        await game.ships.buy_ship(1, "scout")
    await _set_xp(game, 1, 200)  # уровень 3
    await set_ship(game, 1, hp=10, cargo_level=1, energy=40)
    r = await game.ships.buy_ship(1, "scout")
    assert r.cost == 2500 and r.hp == 110 and r.capacity == 40
    p = await game.accounts.profile(1)
    assert p.ship.ship_class == "scout" and p.ship.cargo_level == 1 and p.ship.energy == 40
    with pytest.raises(GameError, match="уже корабль"):
        await game.ships.buy_ship(1, "scout")
    with pytest.raises(GameError, match="нельзя купить"):
        await game.ships.buy_ship(1, "shuttle")


async def test_buy_ship_blocked_when_cargo_does_not_fit(game):
    await make_user(game, 1, balance=50_000)
    await _set_xp(game, 1, 1000)  # уровень 11
    await game.ships.buy_ship(1, "freighter")  # трюм 65
    await give_items(game, 1, titanium=25)  # 50 единиц
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="не поместится"):
        await game.ships.buy_ship(1, "scout")  # трюм 30
    assert await snapshot(game, 1) == before
    with pytest.raises(GameError, match="не поместится"):
        await game.ships.buy_ship(1, "corvette")  # трюм 45 < 50
    assert await snapshot(game, 1) == before


async def test_repair_bounds_and_cost(game):
    await make_user(game, 1)
    with pytest.raises(GameError, match="исправен"):
        await game.ships.repair(1)
    await set_ship(game, 1, hp=40)
    with pytest.raises(ValidationError):
        await game.ships.repair(1, 61)
    with pytest.raises(ValidationError):
        await game.ships.repair(1, 0)
    with pytest.raises(ValidationError):
        await game.ships.repair(1, -5)
    r = await game.ships.repair(1, 10)
    assert (r.repaired, r.cost, r.hp, r.balance) == (10, 50, 50, 950)
    r = await game.ships.repair(1)
    assert (r.repaired, r.cost, r.hp) == (50, 250, 100)


async def test_repair_insufficient_funds_no_change(game):
    await make_user(game, 1, balance=4)
    await set_ship(game, 1, hp=0)
    before = await snapshot(game, 1)
    with pytest.raises(InsufficientFunds):
        await game.ships.repair(1, 1)
    assert await snapshot(game, 1) == before
