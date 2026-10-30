"""PvE-охота на пиратов и общие боевые формулы.

Формулы (зафиксированы):
* Атака игрока = 10 + 4 × оружие + бонус класса + random(1..20).
* PvE: игрок побеждает при атаке >= силы пирата (ничья — в пользу игрока).
* Урон по кораблю = max(1, базовый − 2 × броня); HP не опускается ниже 0.
"""
from __future__ import annotations

import random

from app.constants import (
    ARMOR_DAMAGE_REDUCTION,
    ENEMIES,
    ENEMY_ORDER,
    ENEMY_WEIGHTS,
    HUNT_COOLDOWN,
    HUNT_ENERGY,
    PLAYER_BASE_POWER,
    POWER_ROLL_MAX,
    POWER_ROLL_MIN,
    PVE_LOSS_DAMAGE,
    PVE_WIN_DAMAGE,
    SHIP_CLASSES,
    WEAPON_PER_LEVEL,
    XP_PVE_LOSS,
)
from app.db import repositories as repo
from app.models import HuntResult, Progress, ShipState
from app.services import progression
from app.services.base import ServiceContext, load_ship, require_cooldown, require_hull, save_ship, spend_energy


def attack_power(ship: ShipState, rng: random.Random) -> int:
    return (PLAYER_BASE_POWER + WEAPON_PER_LEVEL * ship.weapon_level
            + SHIP_CLASSES[ship.ship_class].combat_bonus + rng.randint(POWER_ROLL_MIN, POWER_ROLL_MAX))


def mitigate(base_damage: int, armor_level: int) -> int:
    """Снижение урона бронёй; итог не меньше 1 (если базовый урон > 0)."""
    if base_damage <= 0:
        return 0
    return max(1, base_damage - ARMOR_DAMAGE_REDUCTION * armor_level)


def pick_enemy(planet_id: str, rng: random.Random) -> str:
    return rng.choices(ENEMY_ORDER, weights=ENEMY_WEIGHTS[planet_id], k=1)[0]


class CombatService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def hunt(self, user_id: int, token: str | None = None) -> HuntResult:
        rng = self.ctx.rng
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            if token is not None:
                await repo.consume_token(conn, token, user_id, "hunt", now)
            user = await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, now)
            require_hull(ship, "охота")
            require_cooldown(ship.hunt_cooldown_until, now, "Охота")
            spend_energy(ship, HUNT_ENERGY, now)
            ship.hunt_cooldown_until = now + HUNT_COOLDOWN

            enemy = ENEMIES[pick_enemy(user["planet_id"], rng)]
            enemy_power = rng.randint(enemy.power_min, enemy.power_max)
            player_power = attack_power(ship, rng)
            won = player_power >= enemy_power
            progress = Progress()
            if won:
                reward = rng.randint(enemy.reward_min, enemy.reward_max)
                damage = mitigate(rng.randint(*PVE_WIN_DAMAGE), ship.armor_level)
                xp = enemy.xp
            else:
                reward = 0
                damage = mitigate(rng.randint(*PVE_LOSS_DAMAGE), ship.armor_level)
                xp = XP_PVE_LOSS
            ship.hp = max(0, ship.hp - damage)
            await save_ship(conn, ship, now)
            if won:
                await progression.earn(conn, user_id, reward, now)
                await repo.inc_stats(conn, user_id, pve_wins=1)
                await progression.advance_quest(conn, user_id, "daily_pirate", 1, now, progress)
            else:
                await repo.inc_stats(conn, user_id, pve_losses=1)
            await progression.add_xp(conn, user_id, xp, now, progress)
            await progression.check_achievements(conn, user_id, now, progress)
            await repo.add_ledger(conn, user_id, "pve_win" if won else "pve_loss", reward, now,
                                  details=f"{enemy.id}: {player_power} vs {enemy_power}, -{damage} HP")
        return HuntResult(enemy.id, player_power, enemy_power, won, reward, damage, ship.hp, ship.max_hp,
                          ship.energy, progress)
