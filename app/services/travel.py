"""Перелёты по двусторонним маршрутам карты."""

from __future__ import annotations

from app.constants import PLANETS, ROUTES, TRAVEL_COOLDOWN, TRAVEL_MIN_COST, XP_TRAVEL
from app.db import repositories as repo
from app.errors import GameError, StaleAction, ValidationError
from app.models import Progress, TravelResult
from app.services import progression
from app.services.base import ServiceContext, load_ship, require_cooldown, require_hull, save_ship, spend_energy


def travel_cost(base: int, engine_level: int) -> int:
    return max(TRAVEL_MIN_COST, base - engine_level)


class TravelService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def destinations(self, user_id: int) -> tuple[str, dict[str, int]]:
        """Текущая планета и стоимость перелёта к соседям с учётом двигателя."""
        async with self.ctx.db.read() as conn:
            user = await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, self.ctx.clock.now())
        here = user["planet_id"]
        return here, {dest: travel_cost(base, ship.engine_level) for dest, base in ROUTES[here].items()}

    async def travel(self, user_id: int, destination: str, token: str | None = None) -> TravelResult:
        destination = (destination or "").strip().lower()
        if destination not in PLANETS:
            raise ValidationError("❓ Неизвестная планета. Откройте /map.")
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            user = await repo.require_user(conn, user_id)
            here = user["planet_id"]
            if token is not None:
                payload = await repo.consume_token(conn, token, user_id, "travel", now)
                if payload.get("from") != here:
                    raise StaleAction()
            if destination == here:
                raise GameError("📍 Вы уже находитесь на этой планете.")
            if destination not in ROUTES[here]:
                raise GameError(f"🚫 Нет прямого маршрута {PLANETS[here].title} → {PLANETS[destination].title}.")
            ship = await load_ship(conn, user_id, now)
            require_hull(ship, "перелёт")
            require_cooldown(ship.travel_cooldown_until, now, "Следующий перелёт")
            cost = travel_cost(ROUTES[here][destination], ship.engine_level)
            spend_energy(ship, cost, now)
            ship.travel_cooldown_until = now + TRAVEL_COOLDOWN
            await save_ship(conn, ship, now)
            await conn.execute(
                "UPDATE users SET planet_id = ?, updated_at = ? WHERE user_id = ?", (destination, now, user_id)
            )
            progress = Progress()
            await repo.inc_stats(conn, user_id, travels=1)
            await progression.add_xp(conn, user_id, XP_TRAVEL, now, progress)
            await progression.advance_quest(conn, user_id, "daily_travel", 1, now, progress)
            await progression.check_achievements(conn, user_id, now, progress)
        return TravelResult(here, destination, cost, ship.energy, ship.travel_cooldown_until, progress)
