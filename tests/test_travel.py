import pytest

from app.errors import GameError, StaleAction, ValidationError
from tests.conftest import make_user, set_ship, snapshot


async def test_travel_success(game, clock):
    await make_user(game, 1)
    r = await game.travel.travel(1, "mars")
    assert (r.from_planet, r.to_planet, r.energy_cost, r.energy_left) == ("earth", "mars", 10, 90)
    assert r.cooldown_until == clock.now() + 60
    p = await game.accounts.profile(1)
    assert p.planet_id == "mars" and p.xp == 2 and p.stats["travels"] == 1


async def test_illegal_routes_and_same_planet(game):
    await make_user(game, 1)
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="Нет прямого маршрута"):
        await game.travel.travel(1, "titan")
    with pytest.raises(GameError, match="уже находитесь"):
        await game.travel.travel(1, "earth")
    with pytest.raises(ValidationError):
        await game.travel.travel(1, "pluto")
    assert await snapshot(game, 1) == before


async def test_cooldown_and_energy(game, clock):
    await make_user(game, 1)
    await game.travel.travel(1, "venus")
    with pytest.raises(GameError, match="через"):
        await game.travel.travel(1, "earth")
    clock.advance(60)
    await game.travel.travel(1, "earth")
    clock.advance(60)
    await set_ship(game, 1, energy=9, energy_updated_at=clock.now())
    with pytest.raises(GameError, match="энергии"):
        await game.travel.travel(1, "mars")


async def test_engine_reduces_cost_min_5(game):
    await make_user(game, 1)
    await set_ship(game, 1, engine_level=5)
    here, costs = await game.travel.destinations(1)
    assert costs == {"mars": 5, "venus": 5}
    r = await game.travel.travel(1, "mars")
    assert r.energy_cost == 5


async def test_broken_ship_cannot_travel(game):
    await make_user(game, 1)
    await set_ship(game, 1, hp=0)
    with pytest.raises(GameError, match="разрушен"):
        await game.travel.travel(1, "mars")


async def test_old_travel_keyboard_rejected(game, clock):
    await make_user(game, 1)
    token = await game.tokens.issue(1, 1, "travel", {"from": "earth"})
    await game.travel.travel(1, "mars")          # переместились командой
    clock.advance(60)
    with pytest.raises(StaleAction):
        await game.travel.travel(1, "earth", token=token)   # старая клавиатура с Земли
