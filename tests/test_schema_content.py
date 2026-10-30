"""Схема БД и игровой контент: свежая база совпадает с продом и принимает весь контент.

Если тест падает после добавления планеты, товара, корабля, задания или достижения,
нужна новая миграция (пересборка таблицы с новым CHECK и/или seed), а не правка V1.
"""

from __future__ import annotations

import hashlib
import json

from app.constants import (
    ACHIEVEMENTS,
    ITEMS,
    MAX_ENERGY,
    MODULE_MAX_LEVEL,
    PLANETS,
    QUESTS,
    SHIP_CLASSES,
    XP_PER_LEVEL,
)
from app.db.migrations import MIGRATIONS, SEEDS
from app.models import ship_max_hp
from tests.conftest import make_user

# Отпечаток V1 в том виде, в котором она применена на проде.
V1_SQL_SHA256 = "f1b3ae0ce751db84052c940e41374a28cc1dcd4f14106bc9beff60a089d860cd"
V1_SEED_SHA256 = "0d1db676bcd149111053e93c5686d0354cddae2ba325db3c6ef508f68f53b572"


def test_v1_is_frozen():
    version, _, statements = MIGRATIONS[0]
    assert version == 1
    assert hashlib.sha256("\n".join(statements).encode()).hexdigest() == V1_SQL_SHA256
    seed = json.dumps(SEEDS[1](), ensure_ascii=False)
    assert hashlib.sha256(seed.encode()).hexdigest() == V1_SEED_SHA256


async def test_schema_accepts_all_content(game):
    await make_user(game, 1)
    async with game.db.transaction() as conn:
        for item_id in ITEMS:
            await conn.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES (1, ?, 1)", (item_id,))
        for planet_id in PLANETS:
            await conn.execute("UPDATE users SET planet_id = ? WHERE user_id = 1", (planet_id,))
        for ship_class in SHIP_CLASSES:  # класс и максимальная прочность с бронёй максимального уровня
            await conn.execute(
                "UPDATE ships SET ship_class = ?, armor_level = ?, cargo_level = ?, engine_level = ?, "
                "weapon_level = ?, hp = ?, energy = ? WHERE user_id = 1",
                (ship_class, *[MODULE_MAX_LEVEL] * 4, ship_max_hp(ship_class, MODULE_MAX_LEVEL), MAX_ENERGY),
            )
        # CHECK (level = 1 + xp / 100) в V1 — XP_PER_LEVEL зашит в схему.
        await conn.execute("UPDATE users SET xp = ?, level = 2 WHERE user_id = 1", (XP_PER_LEVEL,))
        for quest_id in QUESTS:
            await conn.execute(
                "INSERT INTO user_quests (user_id, quest_date, quest_id) VALUES (1, '2026-01-01', ?)", (quest_id,)
            )
        for achievement_id in ACHIEVEMENTS:  # FK на каталог achievements
            await conn.execute(
                "INSERT INTO user_achievements (user_id, achievement_id, earned_at) VALUES (1, ?, 0)",
                (achievement_id,),
            )
