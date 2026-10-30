"""Добыча ресурсов на текущей планете."""
from __future__ import annotations

from app.constants import ITEMS, MINE_COOLDOWN, MINE_ENERGY, MINE_MAX_UNITS, MINE_MIN_UNITS, MINEABLE, XP_MINE
from app.db import repositories as repo
from app.errors import GameError
from app.models import MineResult, Progress
from app.services import progression
from app.services.base import ServiceContext, load_ship, require_cooldown, require_hull, save_ship, spend_energy


class MiningService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def mine(self, user_id: int, token: str | None = None) -> MineResult:
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            if token is not None:
                await repo.consume_token(conn, token, user_id, "mine", now)
            user = await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, now)
            require_hull(ship, "добыча")
            require_cooldown(ship.mine_cooldown_until, now, "Добыча")
            if ship.energy < MINE_ENERGY:
                spend_energy(ship, MINE_ENERGY, now)       # сформирует сообщение об ошибке
            item_id = self.ctx.rng.choice(MINEABLE[user["planet_id"]])
            qty = self.ctx.rng.randint(MINE_MIN_UNITS, MINE_MAX_UNITS)
            used = repo.cargo_used(await repo.get_inventory(conn, user_id))
            need = qty * ITEMS[item_id].weight
            if used + need > ship.capacity:
                # Отказ до списания энергии и установки кулдауна.
                raise GameError(
                    f"📦 Найдено {qty} × {ITEMS[item_id].title}, но в трюме нет места "
                    f"(нужно {need}, свободно {ship.capacity - used}). Освободите трюм."
                )
            spend_energy(ship, MINE_ENERGY, now)
            ship.mine_cooldown_until = now + MINE_COOLDOWN
            await save_ship(conn, ship, now)
            await repo.add_item(conn, user_id, item_id, qty)
            progress = Progress()
            await repo.inc_stats(conn, user_id, units_mined=qty)
            await progression.add_xp(conn, user_id, XP_MINE, now, progress)
            await progression.advance_quest(conn, user_id, "daily_mine", qty, now, progress)
            await progression.check_achievements(conn, user_id, now, progress)
            await repo.add_ledger(conn, user_id, "mine", 0, now, item_id=item_id, quantity=qty,
                                  details=user["planet_id"])
        return MineResult(item_id, qty, ship.energy, used + need, ship.capacity, progress)
