"""Общие фикстуры: временная SQLite, управляемые часы и детерминированный RNG."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from app.clock import FixedClock
from app.db.connection import Database
from app.services import Game, build_game

# 2026-01-15 12:00:00 UTC
START_TS = int(datetime(2026, 1, 15, 12, 0, tzinfo=UTC).timestamp())
SEED = "test-seed"


class ScriptedRandom(random.Random):
    """RNG с заранее заданными результатами; без сценария — минимум диапазона / первый элемент."""

    def __init__(self) -> None:
        super().__init__(0)
        self.ints: list[int] = []
        self.picks: list[object] = []

    def randint(self, a: int, b: int) -> int:  # type: ignore[override]
        if self.ints:
            value = self.ints.pop(0)
            assert a <= value <= b, f"scripted {value} not in [{a}, {b}]"
            return value
        return a

    def choice(self, seq):  # type: ignore[override]
        if self.picks:
            value = self.picks.pop(0)
            assert value in seq
            return value
        return seq[0]

    def choices(self, population, weights=None, *, cum_weights=None, k=1):  # type: ignore[override]
        if self.picks:
            value = self.picks.pop(0)
            assert value in population
            return [value] * k
        return [population[0]] * k


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test_space_trader.sqlite3")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START_TS)


@pytest.fixture
def rng() -> ScriptedRandom:
    return ScriptedRandom()


@pytest.fixture
async def game(db_path, clock, rng) -> Game:
    db = Database(db_path)
    await db.init()
    return build_game(db, seed=SEED, clock=clock, rng=rng)


async def make_user(
    game: Game, user_id: int, name: str | None = None, balance: int | None = None, planet: str | None = None
) -> None:
    await game.accounts.register(user_id, name or f"Игрок {user_id}")
    async with game.db.transaction() as conn:
        if balance is not None:
            await conn.execute("UPDATE users SET balance = ? WHERE user_id = ?", (balance, user_id))
        if planet is not None:
            await conn.execute("UPDATE users SET planet_id = ? WHERE user_id = ?", (planet, user_id))


async def give_items(game: Game, user_id: int, **items: int) -> None:
    async with game.db.transaction() as conn:
        for item_id, qty in items.items():
            await conn.execute(
                "INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                (user_id, item_id, qty),
            )


async def set_ship(game: Game, user_id: int, **fields) -> None:
    allowed = {
        "ship_class",
        "cargo_level",
        "engine_level",
        "weapon_level",
        "armor_level",
        "hp",
        "energy",
        "energy_updated_at",
        "travel_cooldown_until",
        "mine_cooldown_until",
        "hunt_cooldown_until",
    }
    assert set(fields) <= allowed
    async with game.db.transaction() as conn:
        for k, v in fields.items():
            await conn.execute(f"UPDATE ships SET {k} = ? WHERE user_id = ?", (v, user_id))


async def snapshot(game: Game, user_id: int) -> dict:
    """Полное состояние игрока для проверки «неуспешная операция ничего не меняет»."""
    async with game.db.read() as conn:
        cur = await conn.execute("SELECT balance, xp, level, planet_id FROM users WHERE user_id = ?", (user_id,))
        user = tuple(await cur.fetchone())
        cur = await conn.execute("SELECT * FROM ships WHERE user_id = ?", (user_id,))
        ship = dict(await cur.fetchone())
        ship.pop("updated_at")
        cur = await conn.execute(
            "SELECT item_id, quantity FROM inventory WHERE user_id = ? ORDER BY item_id", (user_id,)
        )
        inv = [tuple(r) for r in await cur.fetchall()]
        cur = await conn.execute("SELECT * FROM player_stats WHERE user_id = ?", (user_id,))
        stats = tuple(await cur.fetchone())
        cur = await conn.execute(
            "SELECT quest_id, progress, claimed FROM user_quests WHERE user_id = ? " "ORDER BY quest_id", (user_id,)
        )
        quests = [tuple(r) for r in await cur.fetchall()]
        cur = await conn.execute("SELECT achievement_id FROM user_achievements WHERE user_id = ?", (user_id,))
        ach = sorted(r[0] for r in await cur.fetchall())
        cur = await conn.execute("SELECT COUNT(*) FROM ledger WHERE user_id = ?", (user_id,))
        ledger = (await cur.fetchone())[0]
    return {"user": user, "ship": ship, "inv": inv, "stats": stats, "quests": quests, "ach": ach, "ledger": ledger}
