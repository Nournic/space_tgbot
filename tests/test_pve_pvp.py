import pytest

from app.errors import GameError, NotYourButton, StaleAction, ValidationError
from tests.conftest import make_user, set_ship, snapshot


async def balance(game, uid):
    return (await game.accounts.profile(uid)).balance


# ------------------------------------------------------------------ PvE
async def test_hunt_win(game, rng):
    await make_user(game, 1)
    rng.picks = ["raider"]
    rng.ints = [15, 10, 80, 10]  # сила пирата, бросок игрока, награда, урон
    r = await game.combat.hunt(1)
    assert r.won and r.player_power == 20 and r.enemy_power == 15
    assert r.reward == 80 and r.damage == 10 and r.hp_left == 90 and r.energy_left == 85
    p = await game.accounts.profile(1)
    assert p.balance == 1080 and p.xp == 15 and p.stats["pve_wins"] == 1 and p.stats["credits_earned"] == 80
    _, quests = await game.quests.today(1)
    assert next(q for q in quests if q.quest_id == "daily_pirate").done


async def test_hunt_tie_goes_to_player(game, rng):
    await make_user(game, 1)
    rng.picks, rng.ints = ["raider"], [15, 5, 60, 5]
    assert (await game.combat.hunt(1)).won


async def test_hunt_loss_and_armor(game, rng):
    await make_user(game, 1)
    await set_ship(game, 1, armor_level=2, hp=125)
    rng.picks = ["frigate"]
    rng.ints = [44, 1, 30]  # поражение, урон 30 − 4 = 26
    r = await game.combat.hunt(1)
    assert not r.won and r.reward == 0 and r.damage == 26 and r.hp_left == 99
    p = await game.accounts.profile(1)
    assert p.balance == 1000 and p.xp == 5 and p.stats["pve_losses"] == 1


async def test_hunt_hp_floor_and_min_damage(game, rng, clock):
    await make_user(game, 1)
    await set_ship(game, 1, hp=10)
    rng.picks, rng.ints = ["raider"], [22, 1, 40]
    r = await game.combat.hunt(1)
    assert r.hp_left == 0
    clock.advance(30)
    with pytest.raises(GameError, match="разрушен"):
        await game.combat.hunt(1)
    # минимальный урон 1 при максимальной броне
    await set_ship(game, 1, armor_level=5, hp=225)
    rng.picks, rng.ints = ["raider"], [10, 20, 60, 5]
    assert (await game.combat.hunt(1)).damage == 1


async def test_hunt_cooldown_and_energy(game, rng, clock):
    await make_user(game, 1)
    await game.combat.hunt(1)
    with pytest.raises(GameError, match="Охота"):
        await game.combat.hunt(1)
    clock.advance(30)
    await set_ship(game, 1, energy=14, energy_updated_at=clock.now())
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="энергии"):
        await game.combat.hunt(1)
    assert await snapshot(game, 1) == before


# ------------------------------------------------------------------ PvP
async def test_challenge_escrow_and_win(game, rng):
    await make_user(game, 1)
    await make_user(game, 2)
    c = await game.pvp.create(1, 2, 100, chat_id=-100)
    assert await balance(game, 1) == 900
    rng.ints = [20, 1, 25, 5]  # бросок A, бросок B, урон проигравшему, урон победителю
    d = await game.pvp.accept(c.id, 2)
    assert d.status == "resolved" and d.winner_id == 1
    assert (d.challenger_power, d.target_power) == (30, 11)
    assert (d.challenger_hp, d.target_hp) == (95, 75)
    assert await balance(game, 1) == 1100 and await balance(game, 2) == 900
    p1, p2 = await game.accounts.profile(1), await game.accounts.profile(2)
    assert (p1.xp, p2.xp) == (20, 5)
    assert p1.stats["pvp_wins"] == 1 and p2.stats["pvp_losses"] == 1
    assert (p1.ship.energy, p2.ship.energy) == (90, 90)
    with pytest.raises(StaleAction):
        await game.pvp.accept(c.id, 2)


async def test_duel_draw_refunds(game, rng):
    await make_user(game, 1)
    await make_user(game, 2)
    c = await game.pvp.create(1, 2, 50, None)
    rng.ints = [7, 7, 3, 0]
    d = await game.pvp.accept(c.id, 2)
    assert d.winner_id is None and d.challenger_xp == 3 and d.target_xp == 3
    assert d.challenger_damage == 3 and d.target_damage == 0
    assert await balance(game, 1) == 1000 and await balance(game, 2) == 1000


async def test_pvp_validation(game):
    await make_user(game, 1, balance=10)
    await make_user(game, 2, planet="mars")
    with pytest.raises(ValidationError):
        await game.pvp.create(1, 1, 0, None)
    with pytest.raises(ValidationError):
        await game.pvp.create(1, 2, -1, None)
    with pytest.raises(GameError, match="другой планете"):
        await game.pvp.create(1, 2, 0, None)
    with pytest.raises(GameError):
        await game.pvp.create(1, 999, 0, None)  # не зарегистрирован
    await make_user(game, 3)
    with pytest.raises(GameError, match="Недостаточно"):
        await game.pvp.create(1, 3, 11, None)


async def test_cancel_decline_permissions(game):
    await make_user(game, 1)
    await make_user(game, 2)
    await make_user(game, 3)
    c = await game.pvp.create(1, 2, 100, None)
    with pytest.raises(NotYourButton):
        await game.pvp.accept(c.id, 3)
    with pytest.raises(NotYourButton):
        await game.pvp.accept(c.id, 1)  # инициатор не может принять
    with pytest.raises(NotYourButton):
        await game.pvp.cancel(c.id, 2)
    v = await game.pvp.decline(c.id, 2)
    assert v.status == "declined" and await balance(game, 1) == 1000
    with pytest.raises(StaleAction):
        await game.pvp.cancel(c.id, 1)
    assert await balance(game, 1) == 1000  # возврат ровно один раз
    c2 = await game.pvp.create(1, 2, 100, None)
    v = await game.pvp.cancel(c2.id, 1)
    assert v.status == "cancelled" and await balance(game, 1) == 1000


async def test_expiry_refunds_once(game, clock):
    await make_user(game, 1)
    await make_user(game, 2)
    c = await game.pvp.create(1, 2, 300, None)
    clock.advance(301)
    d = await game.pvp.accept(c.id, 2)
    assert d.status == "expired" and await balance(game, 1) == 1000
    assert await game.pvp.expire_due() == []
    with pytest.raises(StaleAction):
        await game.pvp.accept(c.id, 2)
    c2 = await game.pvp.create(1, 2, 200, None)
    clock.advance(301)
    notices = await game.pvp.expire_due()
    assert [n.id for n in notices] == [c2.id]
    assert await game.pvp.expire_due() == []
    assert await balance(game, 1) == 1000


async def test_accept_checks_energy_and_keeps_challenge(game, clock):
    await make_user(game, 1)
    await make_user(game, 2)
    c = await game.pvp.create(1, 2, 100, None)
    await set_ship(game, 2, energy=5, energy_updated_at=clock.now())
    with pytest.raises(GameError, match="энергии"):
        await game.pvp.accept(c.id, 2)
    assert (await game.pvp.get(c.id)).status == "pending"
    assert await balance(game, 2) == 1000


async def test_pvp_xp_pair_cooldown(game, rng, clock):
    await make_user(game, 1)
    await make_user(game, 2)
    rng.ints = [20, 1, 20, 0]
    c = await game.pvp.create(1, 2, 0, None)
    d1 = await game.pvp.accept(c.id, 2)
    assert d1.challenger_xp == 20 and not d1.xp_capped
    rng.ints = [1, 20, 20, 0]  # снова побеждает игрок 1
    c = await game.pvp.create(2, 1, 0, None)  # та же пара, обратный порядок
    d2 = await game.pvp.accept(c.id, 1)
    assert d2.challenger_xp == 0 and d2.target_xp == 0 and d2.xp_capped
    assert (await game.accounts.profile(1)).stats["pvp_wins"] == 2  # статистика считается
    clock.advance(3600)
    rng.ints = [20, 1, 20, 0]
    c = await game.pvp.create(1, 2, 0, None)
    assert (await game.pvp.accept(c.id, 2)).challenger_xp == 20
