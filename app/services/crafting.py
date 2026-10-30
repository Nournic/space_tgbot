"""Производство по трём рецептам."""

from __future__ import annotations

from app.constants import CRAFT_FEE_PER_UNIT, ITEMS, MAX_CRAFT_QTY, RECIPES, XP_CRAFT
from app.db import repositories as repo
from app.errors import GameError, StaleAction, ValidationError
from app.models import CraftResult, Progress, ship_capacity
from app.services import progression
from app.services.base import ServiceContext
from app.services.economy import validate_qty


def validate_recipe(item_id: str) -> str:
    item_id = (item_id or "").strip().lower()
    if item_id not in RECIPES:
        raise ValidationError(f"🛠 Нет рецепта для «{item_id[:20]}». Смотрите /recipes.")
    return item_id


class CraftingService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def craft(self, user_id: int, item_id: str, qty: int, token: str | None = None) -> CraftResult:
        item_id = validate_recipe(item_id)
        validate_qty(qty, MAX_CRAFT_QTY)
        recipe = RECIPES[item_id]
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            if token is not None:
                payload = await repo.consume_token(conn, token, user_id, "craft", now)
                if payload.get("item") != item_id or payload.get("qty") != qty:
                    raise StaleAction()
            await repo.require_user(conn, user_id)
            ship = await repo.get_ship(conn, user_id)
            inventory = await repo.get_inventory(conn, user_id)
            reserved = await repo.get_reserved(conn, user_id, now)
            consumed = {ing: per * qty for ing, per in recipe.items()}
            lacking = []
            for ing, need in consumed.items():
                available = inventory.get(ing, 0) - reserved.get(ing, 0)
                if available < need:
                    lacking.append(f"{ITEMS[ing].title}: нужно {need}, доступно {max(0, available)}")
            if lacking:
                raise GameError("🧪 Не хватает ингредиентов:\n" + "\n".join(lacking))
            capacity = ship_capacity(ship["ship_class"], int(ship["cargo_level"]))
            used_after = (
                repo.cargo_used(inventory)
                - sum(ITEMS[i].weight * q for i, q in consumed.items())
                + ITEMS[item_id].weight * qty
            )
            if used_after > capacity:
                raise GameError(f"📦 Результат не поместится в трюм ({used_after} > {capacity}).")
            fee = CRAFT_FEE_PER_UNIT * qty
            balance = await repo.change_balance(conn, user_id, -fee, now)
            for ing, need in consumed.items():
                await repo.remove_item(conn, user_id, ing, need)
            await repo.add_item(conn, user_id, item_id, qty)
            progress = Progress()
            await repo.inc_stats(conn, user_id, crafts=1)
            await progression.add_xp(conn, user_id, XP_CRAFT, now, progress)
            await progression.check_achievements(conn, user_id, now, progress)
            await repo.add_ledger(
                conn,
                user_id,
                "craft",
                -fee,
                now,
                item_id=item_id,
                quantity=qty,
                details=", ".join(f"-{q} {i}" for i, q in consumed.items()),
            )
        return CraftResult(item_id, qty, fee, consumed, balance, progress)
