import sqlite3

import pytest

from app.db.connection import Database
from app.db.migrations import MIGRATIONS, current_version
from app.errors import NotRegistered
from tests.conftest import make_user, snapshot


def test_migration_versions_are_contiguous():
    # Ловит ситуацию, когда в двух ветках параллельно добавили миграцию с одним номером.
    versions = [version for version, _, _ in MIGRATIONS]
    assert versions == list(range(1, len(MIGRATIONS) + 1))
    assert all(statements for _, _, statements in MIGRATIONS)


async def test_register_creates_start_state(game):
    result = await game.accounts.register(1, "Алиса")
    p = result.profile
    assert result.created
    assert (p.balance, p.planet_id, p.level, p.xp) == (1000, "earth", 1, 0)
    assert p.ship.ship_class == "shuttle"
    assert (p.ship.hp, p.ship.max_hp, p.ship.energy, p.ship.capacity) == (100, 100, 100, 20)
    assert p.inventory == {} and p.clan_name is None
    assert all(v == 0 for v in p.stats.values())


async def test_repeat_register_is_idempotent(game, clock):
    await game.accounts.register(1, "Алиса")
    await game.economy.buy(1, "water", 3)
    before = await snapshot(game, 1)
    clock.advance(100)
    result = await game.accounts.register(1, "Алиса")
    assert not result.created
    assert await snapshot(game, 1) == before
    async with game.db.read() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM ships WHERE user_id = 1")
        assert (await cur.fetchone())[0] == 1


async def test_register_updates_display_name_and_escaping_source(game):
    await game.accounts.register(1, "Old")
    await game.accounts.touch_name(1, "<b>New</b>   name")
    p = await game.accounts.profile(1)
    assert p.display_name == "<b>New</b> name"  # хранится как есть, экранируется при выводе


async def test_unregistered_user_errors(game):
    with pytest.raises(NotRegistered):
        await game.accounts.profile(42)
    with pytest.raises(NotRegistered):
        await game.economy.buy(42, "water", 1)


async def test_migrations_create_schema_and_are_repeatable(db_path):
    db = Database(db_path)
    assert await db.init() == MIGRATIONS[-1][0]
    assert await db.init() == MIGRATIONS[-1][0]  # повторный запуск безопасен
    assert await current_version(db) == MIGRATIONS[-1][0]
    async with db.read() as conn:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {r[0] for r in await cur.fetchall()}
        cur = await conn.execute("SELECT COUNT(*) FROM schema_migrations")
        assert (await cur.fetchone())[0] == len(MIGRATIONS)
        cur = await conn.execute("SELECT COUNT(*) FROM achievements")
        assert (await cur.fetchone())[0] == 8
        cur = await conn.execute("PRAGMA foreign_keys")
        assert (await cur.fetchone())[0] == 1
        cur = await conn.execute("PRAGMA journal_mode")
        assert (await cur.fetchone())[0] == "wal"
    for t in (
        "users",
        "ships",
        "inventory",
        "trade_offers",
        "pvp_challenges",
        "user_quests",
        "achievements",
        "user_achievements",
        "player_stats",
        "clans",
        "clan_members",
        "action_tokens",
        "ledger",
    ):
        assert t in tables


async def test_db_constraints(game):
    await make_user(game, 1)
    with pytest.raises(sqlite3.IntegrityError):
        async with game.db.transaction() as conn:
            await conn.execute("UPDATE users SET balance = -1 WHERE user_id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        async with game.db.transaction() as conn:
            await conn.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES (1, 'gold', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        async with game.db.transaction() as conn:
            await conn.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES (999, 'water', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        async with game.db.transaction() as conn:
            await conn.execute("UPDATE ships SET energy = 101 WHERE user_id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        async with game.db.transaction() as conn:
            await conn.execute("UPDATE users SET xp = 250, level = 1 WHERE user_id = 1")  # level = 1 + xp/100
