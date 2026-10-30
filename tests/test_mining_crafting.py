import pytest

from app.errors import GameError, InsufficientFunds, ValidationError
from tests.conftest import give_items, make_user, set_ship, snapshot


async def test_mine_success(game, rng, clock):
    await make_user(game, 1)
    rng.picks = ["iron"]
    rng.ints = [4]
    r = await game.mining.mine(1)
    assert (r.item_id, r.quantity, r.energy_left) == ("iron", 4, 88)
    p = await game.accounts.profile(1)
    assert p.inventory == {"iron": 4} and p.xp == 3 and p.stats["units_mined"] == 4
    _, quests = await game.quests.today(1)
    assert next(q for q in quests if q.quest_id == "daily_mine").progress == 4
    with pytest.raises(GameError, match="Добыча"):
        await game.mining.mine(1)  # кулдаун
    clock.advance(30)
    rng.picks, rng.ints = ["water"], [1]
    await game.mining.mine(1)


async def test_mine_only_allowed_resources(game, rng):
    await make_user(game, 1, planet="titan")
    rng.picks = ["titanium"]
    rng.ints = [3]
    r = await game.mining.mine(1)
    assert r.item_id == "titanium" and r.cargo_used == 6


async def test_mine_no_space_fails_before_spending(game, rng):
    await make_user(game, 1)
    await give_items(game, 1, water=18)
    rng.picks, rng.ints = ["iron"], [3]
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="нет места"):
        await game.mining.mine(1)
    assert await snapshot(game, 1) == before  # ни энергии, ни кулдауна


async def test_mine_requires_energy_and_hull(game, clock):
    await make_user(game, 1)
    await set_ship(game, 1, energy=11, energy_updated_at=clock.now())
    with pytest.raises(GameError, match="энергии"):
        await game.mining.mine(1)
    await set_ship(game, 1, energy=100, hp=0)
    with pytest.raises(GameError, match="разрушен"):
        await game.mining.mine(1)


async def test_craft_success_and_integrity(game):
    await make_user(game, 1)
    await give_items(game, 1, iron=5, silicon=4)
    r = await game.crafting.craft(1, "electronics", 2)
    assert r.fee == 20 and r.consumed == {"iron": 4, "silicon": 4}
    p = await game.accounts.profile(1)
    assert p.inventory == {"iron": 1, "electronics": 2}
    assert p.balance == 980 and p.xp == 2 and p.stats["crafts"] == 1


async def test_craft_failures_change_nothing(game):
    await make_user(game, 1, balance=5)
    await give_items(game, 1, water=4, spice=1)
    before = await snapshot(game, 1)
    with pytest.raises(ValidationError):
        await game.crafting.craft(1, "water", 1)  # сырьё без рецепта
    with pytest.raises(GameError, match="ингредиентов"):
        await game.crafting.craft(1, "medicine", 2)  # spice только 1
    with pytest.raises(InsufficientFunds):
        await game.crafting.craft(1, "medicine", 1)  # работа 10 кр., есть 5
    with pytest.raises(ValidationError):
        await game.crafting.craft(1, "medicine", 0)
    assert await snapshot(game, 1) == before


async def test_craft_ignores_reserved_ingredients(game):
    await make_user(game, 1)
    await make_user(game, 2)
    await give_items(game, 1, water=2, silicon=1)
    await game.offers.create(1, 2, "silicon", 1, 10, None)
    with pytest.raises(GameError, match="ингредиентов"):
        await game.crafting.craft(1, "fuel_cell", 1)
