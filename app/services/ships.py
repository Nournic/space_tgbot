"""Верфь, модули и ремонт.

Правила:
* Покупка корпуса заменяет класс, сохраняя модули, груз и энергию.
  Прочность нового корпуса — полный новый максимум (это новый корпус).
  Текущий класс купить нельзя; «Шаттл» не продаётся.
* Улучшение модуля на уровень n стоит 500 × n. При улучшении брони текущая
  прочность не меняется (растёт только максимум) — бесплатного ремонта нет.
* Ремонт — 5 кредитов за единицу недостающей прочности.
"""

from __future__ import annotations

from app.constants import MODULE_COST_STEP, MODULE_MAX_LEVEL, MODULES, REPAIR_COST_PER_HP, SHIP_CLASSES
from app.db import repositories as repo
from app.errors import GameError, StaleAction, ValidationError
from app.models import RepairResult, ShipPurchaseResult, UpgradeResult, ship_capacity, ship_max_hp
from app.services.base import ServiceContext, load_ship, save_ship


def upgrade_cost(next_level: int) -> int:
    return MODULE_COST_STEP * next_level


def validate_ship_class(raw: str | None) -> str:
    """Класс корабля, который вообще продаётся на верфи (без проверки уровня и денег)."""
    ship_class = (raw or "").strip().lower()
    if ship_class not in SHIP_CLASSES:
        raise ValidationError("❓ Неизвестный класс корабля. Смотрите /shipyard.")
    if SHIP_CLASSES[ship_class].price is None:
        raise GameError("🚫 Этот корабль нельзя купить.")
    return ship_class


class ShipService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def _consume(self, conn, token: str | None, user_id: int, action: str, now: int) -> dict:
        if token is None:
            return {}
        return await repo.consume_token(conn, token, user_id, action, now)

    async def buy_ship(self, user_id: int, ship_class: str, token: str | None = None) -> ShipPurchaseResult:
        ship_class = validate_ship_class(ship_class)
        spec = SHIP_CLASSES[ship_class]
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            payload = await self._consume(conn, token, user_id, "shipyard", now)
            if token is not None and payload.get("ship") != ship_class:  # подтверждали другой корабль
                raise StaleAction()
            user = await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, now)
            if ship.ship_class == ship_class:
                raise GameError("🚫 У вас уже корабль этого класса.")
            if int(user["level"]) < spec.min_level:
                raise GameError(f"⭐ Нужен уровень {spec.min_level}, у вас {user['level']}.")
            capacity = ship_capacity(ship_class, ship.cargo_level)
            used = repo.cargo_used(await repo.get_inventory(conn, user_id))
            if used > capacity:
                raise GameError(f"📦 Груз ({used}) не поместится в трюм нового корпуса ({capacity}). Разгрузитесь.")
            balance = await repo.change_balance(conn, user_id, -spec.price, now)
            new_hp = ship_max_hp(ship_class, ship.armor_level)
            await conn.execute(
                "UPDATE ships SET ship_class = ?, hp = ?, updated_at = ? WHERE user_id = ?",
                (ship_class, new_hp, now, user_id),
            )
            ship.ship_class = ship_class
            ship.hp = new_hp
            await save_ship(conn, ship, now)
            await repo.add_ledger(conn, user_id, "ship_buy", -spec.price, now, details=ship_class)
        return ShipPurchaseResult(ship_class, spec.price, balance, new_hp, capacity)

    async def upgrade(self, user_id: int, module: str, token: str | None = None) -> UpgradeResult:
        module = (module or "").strip().lower()
        if module not in MODULES:
            raise ValidationError("❓ Неизвестный модуль. Доступны: cargo, engine, weapon, armor.")
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            payload = await self._consume(conn, token, user_id, "upgrade", now)
            await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, now)
            current = ship.module_level(module)
            # Кнопка показывала цену для уровня из payload; если уровень уже другой — цена другая.
            if payload.get("levels", {}).get(module, current) != current:
                raise StaleAction()
            if current >= MODULE_MAX_LEVEL:
                raise GameError(f"🔝 {MODULES[module]} уже максимального уровня {MODULE_MAX_LEVEL}.")
            new_level = current + 1
            cost = upgrade_cost(new_level)
            balance = await repo.change_balance(conn, user_id, -cost, now)
            column = {
                "cargo": "cargo_level",
                "engine": "engine_level",
                "weapon": "weapon_level",
                "armor": "armor_level",
            }[module]
            # Условие по старому уровню защищает от гонки двух улучшений.
            cur = await conn.execute(
                f"UPDATE ships SET {column} = ?, updated_at = ? WHERE user_id = ? AND {column} = ?",
                (new_level, now, user_id, current),
            )
            if cur.rowcount != 1:
                raise StaleAction()
            await repo.add_ledger(conn, user_id, "upgrade", -cost, now, details=f"{module}:{new_level}")
        return UpgradeResult(module, new_level, cost, balance)

    async def repair(self, user_id: int, amount: int | None = None, token: str | None = None) -> RepairResult:
        """amount=None — полный ремонт; иначе точное число единиц (не больше недостающих)."""
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int) or amount < 1):
            raise ValidationError("🔢 Количество прочности для ремонта — целое число больше 0.")
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            payload = await self._consume(conn, token, user_id, "repair", now)
            await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, now)
            missing = ship.max_hp - ship.hp
            # Кнопка показывала стоимость ремонта для прежних повреждений.
            if payload.get("missing", missing) != missing:
                raise StaleAction()
            if missing <= 0:
                raise GameError("✅ Корабль полностью исправен.")
            units = missing if amount is None else amount
            if units > missing:
                raise ValidationError(f"🔧 Можно восстановить не больше {missing} ед. прочности.")
            cost = units * REPAIR_COST_PER_HP
            balance = await repo.change_balance(conn, user_id, -cost, now)
            ship.hp += units
            await save_ship(conn, ship, now)
            await repo.add_ledger(conn, user_id, "repair", -cost, now, details=f"+{units} HP")
        return RepairResult(units, cost, ship.hp, ship.max_hp, balance)
