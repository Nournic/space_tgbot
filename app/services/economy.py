"""Динамические цены и системный рынок (покупка/продажа)."""

from __future__ import annotations

from app.clock import utc_date
from app.constants import (
    BASE_PRICES,
    DAILY_DEVIATION_PCT,
    EVENT_MAX_PCT,
    ITEM_ORDER,
    ITEMS,
    MAX_QTY,
    PLANET_ORDER,
    PRICE_MAX_PCT,
    PRICE_MIN_PCT,
    SELL_RATIO_PCT,
    XP_TRADE,
)
from app.db import repositories as repo
from app.errors import GameError, StaleAction, ValidationError
from app.models import Progress, TradeResult, ship_capacity
from app.services import progression
from app.services.base import ServiceContext
from app.services.events import event_for_date, stable_int


def daily_deviation(day: str, planet_id: str, item_id: str, seed: str) -> int:
    """Отклонение в целых процентах −20..+20, одинаковое для всех в пределах UTC-суток."""
    span = 2 * DAILY_DEVIATION_PCT + 1
    return stable_int(seed, "price", day, planet_id, item_id) % span - DAILY_DEVIATION_PCT


def buy_price(day: str, planet_id: str, item_id: str, seed: str) -> int:
    base = BASE_PRICES[planet_id][item_id]
    event_pct = event_for_date(day, seed).modifiers.get(item_id, 0)
    event_pct = max(-EVENT_MAX_PCT, min(EVENT_MAX_PCT, event_pct))
    pct = 100 + daily_deviation(day, planet_id, item_id, seed) + event_pct
    pct = max(PRICE_MIN_PCT, min(PRICE_MAX_PCT, pct))
    return max(1, base * pct // 100)


def sell_price(buy: int) -> int:
    return max(1, buy * SELL_RATIO_PCT // 100)


def validate_item(item_id: str) -> str:
    item_id = (item_id or "").strip().lower()
    if item_id not in ITEMS:
        raise ValidationError(f"❓ Неизвестный товар «{item_id[:20]}». Доступны: {', '.join(ITEM_ORDER)}.")
    return item_id


def validate_qty(qty: int, maximum: int = MAX_QTY) -> int:
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > maximum:
        raise ValidationError(f"🔢 Количество должно быть целым числом от 1 до {maximum}.")
    return qty


class EconomyService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    def prices_on(self, planet_id: str, now: int | None = None) -> dict[str, tuple[int, int]]:
        day = utc_date(self.ctx.clock.now() if now is None else now)
        out = {}
        for item_id in ITEM_ORDER:
            b = buy_price(day, planet_id, item_id, self.ctx.seed)
            out[item_id] = (b, sell_price(b))
        return out

    def price_table(self) -> dict[str, dict[str, tuple[int, int]]]:
        now = self.ctx.clock.now()
        return {p: self.prices_on(p, now) for p in PLANET_ORDER}

    async def buy(self, user_id: int, item_id: str, qty: int, token: str | None = None) -> TradeResult:
        return await self._trade(user_id, "buy", item_id, qty, token)

    async def sell(self, user_id: int, item_id: str, qty: int, token: str | None = None) -> TradeResult:
        return await self._trade(user_id, "sell", item_id, qty, token)

    async def _trade(self, user_id: int, op: str, item_id: str, qty: int, token: str | None) -> TradeResult:
        item_id = validate_item(item_id)
        validate_qty(qty)
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            user = await repo.require_user(conn, user_id)
            if token is not None:
                payload = await repo.consume_token(conn, token, user_id, "market", now)
                if payload.get("planet") != user["planet_id"] or payload.get("item") != item_id:
                    raise StaleAction()
                if payload.get("date", utc_date(now)) != utc_date(now):  # цены карточки — вчерашние
                    raise StaleAction()
            planet = user["planet_id"]
            # Цена берётся на сервере внутри транзакции, а не из кнопки.
            unit_buy = buy_price(utc_date(now), planet, item_id, self.ctx.seed)
            ship = await repo.get_ship(conn, user_id)
            inventory = await repo.get_inventory(conn, user_id)
            capacity = ship_capacity(ship["ship_class"], int(ship["cargo_level"]))
            used = repo.cargo_used(inventory)
            progress = Progress()
            weight = ITEMS[item_id].weight
            if op == "buy":
                unit = unit_buy
                total = unit * qty
                if used + weight * qty > capacity:
                    free = capacity - used
                    raise GameError(
                        f"📦 Не хватает места в трюме: нужно {weight * qty}, свободно {free} из {capacity}."
                    )
                balance = await repo.change_balance(conn, user_id, -total, now)
                await repo.add_item(conn, user_id, item_id, qty)
                await repo.inc_stats(conn, user_id, trades=1, units_bought=qty)
                used += weight * qty
                kind = "market_buy"
                amount = -total
            else:
                unit = sell_price(unit_buy)
                total = unit * qty
                reserved = await repo.get_reserved(conn, user_id, now)
                available = inventory.get(item_id, 0) - reserved.get(item_id, 0)
                if available < qty:
                    extra = f" (ещё {reserved[item_id]} в резерве P2P)" if reserved.get(item_id) else ""
                    raise GameError(f"📦 Недостаточно товара: доступно {max(0, available)}{extra}.")
                await repo.remove_item(conn, user_id, item_id, qty)
                balance = await progression.earn(conn, user_id, total, now)
                await repo.inc_stats(conn, user_id, trades=1, units_sold=qty)
                await progression.advance_quest(conn, user_id, "daily_sell", qty, now, progress)
                used -= weight * qty
                kind = "market_sell"
                amount = total
            await repo.add_ledger(
                conn, user_id, kind, amount, now, item_id=item_id, quantity=qty if op == "buy" else -qty, details=planet
            )
            await progression.add_xp(conn, user_id, XP_TRADE, now, progress)
            await progression.check_achievements(conn, user_id, now, progress)
            owned = (await repo.get_inventory(conn, user_id)).get(item_id, 0)
        return TradeResult(
            op=op,
            item_id=item_id,
            quantity=qty,
            unit_price=unit,
            total=total,
            balance=balance,
            cargo_used=used,
            capacity=capacity,
            owned=owned,
            progress=progress,
        )
