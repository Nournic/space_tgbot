import asyncio

import pytest

from app.errors import GameError, NotYourButton, StaleAction, ValidationError
from tests.conftest import give_items, make_user


async def setup_pair(game):
    await make_user(game, 1, "Продавец")
    await make_user(game, 2, "Покупатель")
    await give_items(game, 1, water=10)


async def test_reserve_reduces_available_not_cargo(game):
    await setup_pair(game)
    await game.offers.create(1, 2, "water", 6, 100, None)
    p = await game.accounts.profile(1)
    assert p.inventory["water"] == 10 and p.reserved["water"] == 6 and p.cargo_used == 10
    with pytest.raises(GameError, match="доступно 4"):
        await game.economy.sell(1, "water", 5)
    await game.economy.sell(1, "water", 4)
    with pytest.raises(GameError):
        await game.offers.create(1, 2, "water", 1, 0, None)  # всё в резерве


async def test_cancel_releases_reserve(game):
    await setup_pair(game)
    o = await game.offers.create(1, 2, "water", 6, 100, None)
    with pytest.raises(NotYourButton):
        await game.offers.cancel(o.id, 2)
    out = await game.offers.cancel(o.id, 1)
    assert out.status == "cancelled"
    p = await game.accounts.profile(1)
    assert p.reserved == {} and p.inventory["water"] == 10
    with pytest.raises(StaleAction):
        await game.offers.accept(o.id, 2)


async def test_accept_transfers_goods_and_money(game):
    await setup_pair(game)
    o = await game.offers.create(1, 2, "water", 5, 200, None)
    out = await game.offers.accept(o.id, 2)
    assert out.status == "accepted"
    s, b = await game.accounts.profile(1), await game.accounts.profile(2)
    assert s.inventory["water"] == 5 and s.balance == 1200 and s.reserved == {}
    assert b.inventory["water"] == 5 and b.balance == 800
    assert s.balance + b.balance == 2000  # P2P не создаёт кредиты
    with pytest.raises(StaleAction):
        await game.offers.accept(o.id, 2)


async def test_gift_zero_price(game):
    await setup_pair(game)
    o = await game.offers.create(1, 2, "water", 1, 0, None)
    await game.offers.accept(o.id, 2)
    assert (await game.accounts.profile(2)).inventory == {"water": 1}


async def test_accept_foreign_expired_and_checks(game, clock):
    await setup_pair(game)
    await make_user(game, 3)
    o = await game.offers.create(1, 2, "water", 5, 200, None)
    with pytest.raises(NotYourButton):
        await game.offers.accept(o.id, 3)
    with pytest.raises(NotYourButton):
        await game.offers.accept(o.id, 1)
    clock.advance(301)
    out = await game.offers.accept(o.id, 2)
    assert out.status == "expired"
    assert (await game.accounts.profile(2)).inventory == {}
    assert (await game.accounts.profile(1)).reserved == {}


async def test_accept_requires_funds_and_space(game):
    await setup_pair(game)
    o = await game.offers.create(1, 2, "water", 5, 5000, None)
    with pytest.raises(GameError, match="кредитов"):
        await game.offers.accept(o.id, 2)
    await give_items(game, 2, iron=18)
    o2 = await game.offers.create(1, 2, "water", 3, 1, None)
    with pytest.raises(GameError, match="места"):
        await game.offers.accept(o2.id, 2)
    assert (await game.offers.get(o2.id)).status == "pending"


async def test_offer_validation(game):
    await setup_pair(game)
    with pytest.raises(ValidationError):
        await game.offers.create(1, 1, "water", 1, 1, None)
    with pytest.raises(ValidationError):
        await game.offers.create(1, 2, "water", 0, 1, None)
    with pytest.raises(ValidationError):
        await game.offers.create(1, 2, "water", 1, -1, None)
    with pytest.raises(ValidationError):
        await game.offers.create(1, 2, "unobtainium", 1, 1, None)


async def test_concurrent_accept_only_once(game):
    await setup_pair(game)
    o = await game.offers.create(1, 2, "water", 5, 100, None)
    results = await asyncio.gather(*(game.offers.accept(o.id, 2) for _ in range(8)), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1
    assert all(isinstance(r, StaleAction) for r in results if isinstance(r, Exception))
    s, b = await game.accounts.profile(1), await game.accounts.profile(2)
    assert (s.balance, b.balance) == (1100, 900)
    assert (s.inventory["water"], b.inventory["water"]) == (5, 5)


async def test_multiple_offers_reservations_consistent(game):
    await setup_pair(game)
    await make_user(game, 3)
    o1 = await game.offers.create(1, 2, "water", 4, 10, None)
    o2 = await game.offers.create(1, 3, "water", 6, 10, None)
    await game.offers.accept(o1.id, 2)
    p = await game.accounts.profile(1)
    assert p.inventory["water"] == 6 and p.reserved["water"] == 6
    await game.offers.accept(o2.id, 3)
    assert (await game.accounts.profile(1)).inventory == {}
