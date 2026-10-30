"""Версионированные миграции схемы.

Версия хранится в ``PRAGMA user_version`` и дублируется журналом в
``schema_migrations``. Каждая миграция применяется в одной транзакции,
повторный запуск безопасен (уже применённые версии пропускаются).
Для обновления версии 1.0 добавьте новый элемент в MIGRATIONS.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.constants import ACHIEVEMENT_ORDER, ACHIEVEMENTS, ITEM_ORDER, PLANET_ORDER, SHIP_ORDER

if TYPE_CHECKING:
    from app.db.connection import Database

log = logging.getLogger(__name__)


def _in_list(values: tuple[str, ...]) -> str:
    # Значения — только внутренние константы, не пользовательский ввод.
    return ", ".join(f"'{v}'" for v in values)


PLANETS_SQL = _in_list(PLANET_ORDER)
ITEMS_SQL = _in_list(ITEM_ORDER)
SHIPS_SQL = _in_list(SHIP_ORDER)

V1: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version     INTEGER PRIMARY KEY,
        description TEXT    NOT NULL,
        applied_at  INTEGER NOT NULL
    )
    """,
    f"""
    CREATE TABLE users (
        user_id      INTEGER PRIMARY KEY,
        display_name TEXT    NOT NULL CHECK (length(display_name) BETWEEN 1 AND 64),
        balance      INTEGER NOT NULL CHECK (balance >= 0),
        planet_id    TEXT    NOT NULL CHECK (planet_id IN ({PLANETS_SQL})),
        xp           INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
        level        INTEGER NOT NULL DEFAULT 1 CHECK (level = 1 + xp / 100),
        created_at   INTEGER NOT NULL,
        updated_at   INTEGER NOT NULL
    )
    """,
    f"""
    CREATE TABLE ships (
        user_id               INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
        ship_class            TEXT    NOT NULL CHECK (ship_class IN ({SHIPS_SQL})),
        cargo_level           INTEGER NOT NULL DEFAULT 0 CHECK (cargo_level BETWEEN 0 AND 5),
        engine_level          INTEGER NOT NULL DEFAULT 0 CHECK (engine_level BETWEEN 0 AND 5),
        weapon_level          INTEGER NOT NULL DEFAULT 0 CHECK (weapon_level BETWEEN 0 AND 5),
        armor_level           INTEGER NOT NULL DEFAULT 0 CHECK (armor_level BETWEEN 0 AND 5),
        hp                    INTEGER NOT NULL CHECK (hp >= 0 AND hp <= 315),
        energy                INTEGER NOT NULL CHECK (energy BETWEEN 0 AND 100),
        energy_updated_at     INTEGER NOT NULL,
        travel_cooldown_until INTEGER NOT NULL DEFAULT 0,
        mine_cooldown_until   INTEGER NOT NULL DEFAULT 0,
        hunt_cooldown_until   INTEGER NOT NULL DEFAULT 0,
        created_at            INTEGER NOT NULL,
        updated_at            INTEGER NOT NULL
    )
    """,
    f"""
    CREATE TABLE inventory (
        user_id  INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        item_id  TEXT    NOT NULL CHECK (item_id IN ({ITEMS_SQL})),
        quantity INTEGER NOT NULL CHECK (quantity >= 0),
        PRIMARY KEY (user_id, item_id)
    )
    """,
    f"""
    CREATE TABLE trade_offers (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id   INTEGER NOT NULL REFERENCES users(user_id),
        buyer_id    INTEGER NOT NULL REFERENCES users(user_id),
        item_id     TEXT    NOT NULL CHECK (item_id IN ({ITEMS_SQL})),
        quantity    INTEGER NOT NULL CHECK (quantity > 0),
        price       INTEGER NOT NULL CHECK (price >= 0),
        status      TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')),
        chat_id     INTEGER,
        message_id  INTEGER,
        created_at  INTEGER NOT NULL,
        expires_at  INTEGER NOT NULL,
        resolved_at INTEGER,
        CHECK (seller_id <> buyer_id)
    )
    """,
    "CREATE INDEX idx_offers_seller_status ON trade_offers(seller_id, status, item_id)",
    "CREATE INDEX idx_offers_buyer_status ON trade_offers(buyer_id, status)",
    "CREATE INDEX idx_offers_status_expiry ON trade_offers(status, expires_at)",
    """
    CREATE TABLE pvp_challenges (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id    INTEGER NOT NULL REFERENCES users(user_id),
        target_id        INTEGER NOT NULL REFERENCES users(user_id),
        stake            INTEGER NOT NULL CHECK (stake >= 0),
        status           TEXT    NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'resolved', 'declined', 'cancelled', 'expired')),
        chat_id          INTEGER,
        message_id       INTEGER,
        created_at       INTEGER NOT NULL,
        expires_at       INTEGER NOT NULL,
        resolved_at      INTEGER,
        winner_id        INTEGER REFERENCES users(user_id),
        challenger_power INTEGER,
        target_power     INTEGER,
        CHECK (challenger_id <> target_id)
    )
    """,
    "CREATE INDEX idx_pvp_status_expiry ON pvp_challenges(status, expires_at)",
    "CREATE INDEX idx_pvp_challenger ON pvp_challenges(challenger_id, status)",
    "CREATE INDEX idx_pvp_target ON pvp_challenges(target_id, status)",
    """
    CREATE TABLE pvp_xp_cooldowns (
        user_a     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        user_b     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        last_xp_at INTEGER NOT NULL,
        PRIMARY KEY (user_a, user_b),
        CHECK (user_a < user_b)
    )
    """,
    """
    CREATE TABLE user_quests (
        user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        quest_date TEXT    NOT NULL,
        quest_id   TEXT    NOT NULL CHECK (quest_id IN ('daily_sell', 'daily_travel', 'daily_mine', 'daily_pirate')),
        progress   INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0),
        claimed    INTEGER NOT NULL DEFAULT 0 CHECK (claimed IN (0, 1)),
        claimed_at INTEGER,
        PRIMARY KEY (user_id, quest_date, quest_id)
    )
    """,
    """
    CREATE TABLE achievements (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE user_achievements (
        user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        achievement_id TEXT    NOT NULL REFERENCES achievements(id),
        earned_at      INTEGER NOT NULL,
        PRIMARY KEY (user_id, achievement_id)
    )
    """,
    """
    CREATE TABLE player_stats (
        user_id          INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
        trades           INTEGER NOT NULL DEFAULT 0 CHECK (trades >= 0),
        units_bought     INTEGER NOT NULL DEFAULT 0 CHECK (units_bought >= 0),
        units_sold       INTEGER NOT NULL DEFAULT 0 CHECK (units_sold >= 0),
        travels          INTEGER NOT NULL DEFAULT 0 CHECK (travels >= 0),
        units_mined      INTEGER NOT NULL DEFAULT 0 CHECK (units_mined >= 0),
        crafts           INTEGER NOT NULL DEFAULT 0 CHECK (crafts >= 0),
        pve_wins         INTEGER NOT NULL DEFAULT 0 CHECK (pve_wins >= 0),
        pve_losses       INTEGER NOT NULL DEFAULT 0 CHECK (pve_losses >= 0),
        pvp_wins         INTEGER NOT NULL DEFAULT 0 CHECK (pvp_wins >= 0),
        pvp_losses       INTEGER NOT NULL DEFAULT 0 CHECK (pvp_losses >= 0),
        pvp_draws        INTEGER NOT NULL DEFAULT 0 CHECK (pvp_draws >= 0),
        quests_completed INTEGER NOT NULL DEFAULT 0 CHECK (quests_completed >= 0),
        credits_earned   INTEGER NOT NULL DEFAULT 0 CHECK (credits_earned >= 0)
    )
    """,
    """
    CREATE TABLE clans (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL CHECK (length(name) BETWEEN 3 AND 32),
        name_key   TEXT    NOT NULL UNIQUE,
        leader_id  INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
        treasury   INTEGER NOT NULL DEFAULT 0 CHECK (treasury >= 0),
        is_open    INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE clan_members (
        user_id   INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
        clan_id   INTEGER NOT NULL REFERENCES clans(id) ON DELETE CASCADE,
        joined_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX idx_clan_members_clan ON clan_members(clan_id)",
    """
    CREATE TABLE action_tokens (
        token      TEXT    PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        chat_id    INTEGER,
        action     TEXT    NOT NULL,
        payload    TEXT    NOT NULL DEFAULT '{}',
        status     TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'used', 'expired')),
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        used_at    INTEGER
    )
    """,
    "CREATE INDEX idx_tokens_status_expiry ON action_tokens(status, expires_at)",
    """
    CREATE TABLE ledger (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        kind            TEXT    NOT NULL,
        amount          INTEGER NOT NULL,
        balance_after   INTEGER NOT NULL CHECK (balance_after >= 0),
        item_id         TEXT,
        quantity        INTEGER,
        counterparty_id INTEGER,
        ref_type        TEXT,
        ref_id          INTEGER,
        details         TEXT,
        created_at      INTEGER NOT NULL
    )
    """,
    "CREATE INDEX idx_ledger_user ON ledger(user_id, id DESC)",
    "CREATE INDEX idx_users_balance ON users(balance DESC, user_id)",
    "CREATE INDEX idx_users_xp ON users(xp DESC, user_id)",
]

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "Космический Трейдер 1.0: начальная схема", V1),
]


def _seed_v1() -> list[tuple[str, tuple]]:
    return [
        ("INSERT OR IGNORE INTO achievements (id, title, description) VALUES (?, ?, ?)",
         (a.id, a.title, a.description))
        for a in (ACHIEVEMENTS[k] for k in ACHIEVEMENT_ORDER)
    ]


SEEDS = {1: _seed_v1}


async def current_version(db: "Database") -> int:
    conn = await db.connect()
    try:
        cur = await conn.execute("PRAGMA user_version")
        return int((await cur.fetchone())[0])
    finally:
        await conn.close()


async def apply_migrations(db: "Database") -> int:
    version = await current_version(db)
    for target, description, statements in MIGRATIONS:
        if target <= version:
            continue
        async with db.transaction() as conn:
            cur = await conn.execute("PRAGMA user_version")
            if int((await cur.fetchone())[0]) >= target:   # применено параллельным процессом
                continue
            for sql in statements:
                await conn.execute(sql)
            seed = SEEDS.get(target)
            if seed:
                for sql, params in seed():
                    await conn.execute(sql, params)
            await conn.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (target, description, int(time.time())),
            )
            await conn.execute(f"PRAGMA user_version = {int(target)}")
        log.info("Применена миграция %s: %s", target, description)
        version = target
    return version
