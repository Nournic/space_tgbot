"""Общий контекст сервисов и операции над состоянием корабля (энергия, кулдауны)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.clock import Clock
from app.constants import ENERGY_REGEN_SECONDS, MAX_ENERGY
from app.db import repositories as repo
from app.db.connection import Conn, Database
from app.errors import GameError
from app.models import ShipState


@dataclass
class ServiceContext:
    db: Database
    clock: Clock
    rng: random.Random
    seed: str


def regen_energy(energy: int, anchor: int, now: int) -> tuple[int, int]:
    """Ленивая регенерация: +1 за каждые полные 5 минут, остаток интервала сохраняется.

    Если запас полон, якорь переносится на ``now`` — время, проведённое на
    максимуме, не накапливается в «скрытый запас».
    """
    if energy >= MAX_ENERGY:
        return MAX_ENERGY, now
    if now <= anchor:
        return energy, anchor
    intervals = (now - anchor) // ENERGY_REGEN_SECONDS
    new_energy = energy + intervals
    if new_energy >= MAX_ENERGY:
        return MAX_ENERGY, now
    return new_energy, anchor + intervals * ENERGY_REGEN_SECONDS


def ship_from_row(row, now: int) -> ShipState:
    energy, anchor = regen_energy(int(row["energy"]), int(row["energy_updated_at"]), now)
    return ShipState(
        user_id=int(row["user_id"]),
        ship_class=row["ship_class"],
        cargo_level=int(row["cargo_level"]),
        engine_level=int(row["engine_level"]),
        weapon_level=int(row["weapon_level"]),
        armor_level=int(row["armor_level"]),
        hp=int(row["hp"]),
        energy=energy,
        energy_anchor=anchor,
        travel_cooldown_until=int(row["travel_cooldown_until"]),
        mine_cooldown_until=int(row["mine_cooldown_until"]),
        hunt_cooldown_until=int(row["hunt_cooldown_until"]),
    )


async def load_ship(conn: Conn, user_id: int, now: int) -> ShipState:
    return ship_from_row(await repo.get_ship(conn, user_id), now)


async def save_ship(conn: Conn, ship: ShipState, now: int) -> None:
    """Сохраняет изменяемые поля корабля (энергия с якорем, HP, кулдауны)."""
    if not (0 <= ship.energy <= MAX_ENERGY) or not (0 <= ship.hp <= ship.max_hp):
        raise RuntimeError("ship invariant violated")
    await conn.execute(
        "UPDATE ships SET energy = ?, energy_updated_at = ?, hp = ?, travel_cooldown_until = ?, "
        "mine_cooldown_until = ?, hunt_cooldown_until = ?, updated_at = ? WHERE user_id = ?",
        (ship.energy, ship.energy_anchor, ship.hp, ship.travel_cooldown_until,
         ship.mine_cooldown_until, ship.hunt_cooldown_until, now, ship.user_id),
    )


def spend_energy(ship: ShipState, amount: int, now: int) -> None:
    if ship.energy < amount:
        wait = ship.seconds_to_next_energy(now) or 0
        missing = amount - ship.energy
        eta = wait + (missing - 1) * ENERGY_REGEN_SECONDS
        raise GameError(
            f"🔋 Недостаточно энергии: нужно {amount}, есть {ship.energy}. "
            f"Восстановится примерно через {format_duration(eta)}."
        )
    if ship.energy >= MAX_ENERGY:
        ship.energy_anchor = now      # отсчёт регенерации начинается с момента расхода
    ship.energy -= amount


def require_hull(ship: ShipState, action: str) -> None:
    if ship.hp <= 0:
        raise GameError(f"🛠 Корабль разрушен (HP 0) — {action} невозможна. Выполните /repair.")


def require_cooldown(until: int, now: int, action: str) -> None:
    if now < until:
        raise GameError(f"⏱ {action} будет доступна через {format_duration(until - now)}.")


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} сек."
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин. {sec} сек." if sec else f"{minutes} мин."
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч. {minutes} мин."
