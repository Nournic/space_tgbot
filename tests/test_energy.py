from app.services.base import regen_energy
from tests.conftest import make_user, set_ship


def test_regen_keeps_partial_interval():
    energy, anchor = regen_energy(50, 1000, 1000 + 299)
    assert (energy, anchor) == (50, 1000)
    energy, anchor = regen_energy(50, 1000, 1000 + 301)
    assert (energy, anchor) == (51, 1300)  # остаток 1 сек. сохранён
    energy, anchor = regen_energy(energy, anchor, 1000 + 600)
    assert (energy, anchor) == (52, 1600)


def test_regen_caps_at_max_and_resets_anchor():
    assert regen_energy(99, 0, 10_000) == (100, 10_000)
    assert regen_energy(100, 0, 50_000) == (100, 50_000)  # время на максимуме не копится


async def test_lazy_regen_through_service(game, clock):
    await make_user(game, 1)
    await game.travel.travel(1, "mars")  # 100 → 90, якорь = now
    clock.advance(5 * 300 + 120)
    p = await game.accounts.profile(1)
    assert p.ship.energy == 95
    assert p.ship.seconds_to_next_energy(clock.now()) == 180


async def test_no_hidden_stock_after_full(game, clock):
    await make_user(game, 1)
    clock.advance(10 * 3600)  # долго на максимуме
    await game.travel.travel(1, "mars")  # 90
    clock.advance(299)
    assert (await game.accounts.profile(1)).ship.energy == 90
    clock.advance(1)
    assert (await game.accounts.profile(1)).ship.energy == 91


async def test_regen_survives_restart(game, clock, db_path, rng):
    from app.db.connection import Database
    from app.services import build_game

    await make_user(game, 1)
    await set_ship(game, 1, energy=10, energy_updated_at=clock.now())
    clock.advance(3 * 300 + 10)
    restarted = build_game(Database(db_path), seed="test-seed", clock=clock, rng=rng)
    assert (await restarted.accounts.profile(1)).ship.energy == 13
