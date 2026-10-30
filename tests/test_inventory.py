import pytest

from app.errors import GameError
from tests.conftest import give_items, make_user, snapshot


async def test_cargo_weight_counts_per_item(game):
    await make_user(game, 1, balance=100_000)
    r = await game.economy.buy(1, "titanium", 10)       # вес 2 → 20/20
    assert r.cargo_used == 20 and r.capacity == 20
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="места"):
        await game.economy.buy(1, "water", 1)
    assert await snapshot(game, 1) == before


async def test_cannot_overflow_with_heavy_item(game):
    await make_user(game, 1, balance=100_000)
    await game.economy.buy(1, "water", 19)
    with pytest.raises(GameError):
        await game.economy.buy(1, "electronics", 1)     # вес 2, свободно 1
    await game.economy.buy(1, "water", 1)
    p = await game.accounts.profile(1)
    assert p.cargo_used == 20


async def test_sell_reduces_and_removes_rows(game):
    await make_user(game, 1)
    await give_items(game, 1, iron=3)
    await game.economy.sell(1, "iron", 3)
    async with game.db.read() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM inventory WHERE user_id = 1")
        assert (await cur.fetchone())[0] == 0
    with pytest.raises(GameError):
        await game.economy.sell(1, "iron", 1)


async def test_history_is_private_and_paginated(game):
    await make_user(game, 1)
    await make_user(game, 2)
    for _ in range(12):
        await game.economy.buy(1, "water", 1)
    h1 = await game.accounts.history(1, 0)
    h2 = await game.accounts.history(1, 1)
    assert h1.total == 13 and h1.pages == 2 and len(h1.entries) == 10 and len(h2.entries) == 3
    other = await game.accounts.history(2, 0)
    assert other.total == 1 and other.entries[0].kind == "register"
