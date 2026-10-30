import pytest

from app.clock import utc_date
from app.constants import BASE_PRICES, ITEM_ORDER, PLANET_ORDER
from app.db.connection import Database
from app.errors import GameError, InsufficientFunds, ValidationError
from app.services import build_game
from app.services.economy import buy_price, daily_deviation, sell_price
from app.services.events import event_for_date
from tests.conftest import SEED, START_TS, give_items, make_user, snapshot


async def test_buy_and_sell_on_different_planets(game, clock):
    await make_user(game, 1)
    earth = game.economy.prices_on("earth")["water"][0]
    r = await game.economy.buy(1, "water", 5)
    assert r.total == earth * 5 and r.balance == 1000 - earth * 5 and r.owned == 5
    await make_user(game, 2, planet="titan")
    await give_items(game, 2, water=4)
    titan_sell = game.economy.prices_on("titan")["water"][1]
    s = await game.economy.sell(2, "water", 4)
    assert s.total == titan_sell * 4 and s.balance == 1000 + titan_sell * 4 and s.owned == 0
    p = await game.accounts.profile(2)
    assert p.stats["units_sold"] == 4 and p.stats["trades"] == 1 and p.xp == 1


def test_prices_within_bounds_and_sell_lower():
    for day in ("2026-01-01", "2026-06-30", "2027-03-03"):
        for planet in PLANET_ORDER:
            for item in ITEM_ORDER:
                base = BASE_PRICES[planet][item]
                dev = daily_deviation(day, planet, item, SEED)
                assert -20 <= dev <= 20
                b = buy_price(day, planet, item, SEED)
                assert base * 70 // 100 <= b <= base * 130 // 100
                assert sell_price(b) < b  # мгновенная перепродажа убыточна


async def test_prices_stable_within_day_and_after_restart(db_path, clock, rng):
    db = Database(db_path)
    await db.init()
    g1 = build_game(db, seed=SEED, clock=clock, rng=rng)
    first = g1.economy.price_table()
    clock.advance(3600 * 5)  # тот же день UTC (12:00 → 17:00)
    g2 = build_game(Database(db_path), seed=SEED, clock=clock, rng=rng)  # «перезапуск»
    assert g2.economy.price_table() == first


async def test_prices_change_on_new_utc_day(game, clock):
    day1 = game.economy.price_table()
    clock.advance(86_400)
    day2 = game.economy.price_table()
    assert day1 != day2


def test_event_modifier_applies():
    # Находим день с «дефицитом воды» и проверяем, что цена воды = база × (100+откл+10)%.
    for i in range(400):
        day = utc_date(START_TS + i * 86_400)
        if event_for_date(day, SEED).id == "water_shortage":
            for planet in PLANET_ORDER:
                pct = max(70, min(130, 100 + daily_deviation(day, planet, "water", SEED) + 10))
                assert buy_price(day, planet, "water", SEED) == max(1, BASE_PRICES[planet]["water"] * pct // 100)
            return
    pytest.fail("событие не найдено")


async def test_invalid_item_qty_and_funds(game):
    await make_user(game, 1, balance=5)
    before = await snapshot(game, 1)
    with pytest.raises(ValidationError):
        await game.economy.buy(1, "gold", 1)
    for bad in (0, -3, 10_001):
        with pytest.raises(ValidationError):
            await game.economy.buy(1, "water", bad)
    with pytest.raises(InsufficientFunds):
        await game.economy.buy(1, "electronics", 1)
    with pytest.raises(GameError):
        await game.economy.sell(1, "water", 1)
    assert await snapshot(game, 1) == before


async def test_market_token_single_use_and_planet_bound(game):
    await make_user(game, 1)
    token = await game.tokens.issue(1, 100, "market", {"planet": "earth", "item": "water"})
    await game.economy.buy(1, "water", 1, token=token)
    with pytest.raises(GameError, match="устарело"):
        await game.economy.buy(1, "water", 1, token=token)
    token2 = await game.tokens.issue(1, 100, "market", {"planet": "mars", "item": "water"})
    with pytest.raises(GameError, match="устарело"):
        await game.economy.buy(1, "water", 1, token=token2)
