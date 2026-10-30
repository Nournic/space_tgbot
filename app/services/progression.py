"""XP, уровни, прогресс ежедневных заданий и достижения.

Функции вызываются внутри транзакции бизнес-операции, поэтому награды,
счётчики и прогресс фиксируются или откатываются вместе с ней.
"""

from __future__ import annotations

from app.clock import utc_date
from app.constants import ACHIEVEMENT_ORDER, ACHIEVEMENTS, QUESTS, level_for_xp
from app.db import repositories as repo
from app.db.connection import Conn
from app.models import AchievementStatus, Progress


async def add_xp(conn: Conn, user_id: int, amount: int, now: int, progress: Progress) -> None:
    if amount < 0:
        raise ValueError("xp must be non-negative")
    cur = await conn.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,))
    old_xp = int((await cur.fetchone())[0])
    new_xp = old_xp + amount
    old_level, new_level = level_for_xp(old_xp), level_for_xp(new_xp)
    if amount:
        await conn.execute(
            "UPDATE users SET xp = ?, level = ?, updated_at = ? WHERE user_id = ?",
            (new_xp, new_level, now, user_id),
        )
    progress.merge_level(old_level, new_level, amount)


async def earn(conn: Conn, user_id: int, amount: int, now: int) -> int:
    """Начисляет кредиты как доход (учитывается в обороте credits_earned)."""
    balance = await repo.change_balance(conn, user_id, amount, now)
    if amount > 0:
        await repo.inc_stats(conn, user_id, credits_earned=amount)
    return balance


async def advance_quest(conn: Conn, user_id: int, quest_id: str, amount: int, now: int, progress: Progress) -> None:
    """Увеличивает прогресс задания текущих UTC-суток, ограничивая его целью."""
    if amount <= 0:
        return
    quest = QUESTS[quest_id]
    day = utc_date(now)
    cur = await conn.execute(
        "SELECT progress FROM user_quests WHERE user_id = ? AND quest_date = ? AND quest_id = ?",
        (user_id, day, quest_id),
    )
    row = await cur.fetchone()
    before = int(row[0]) if row else 0
    after = min(quest.target, before + amount)
    await conn.execute(
        "INSERT INTO user_quests (user_id, quest_date, quest_id, progress) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, quest_date, quest_id) DO UPDATE SET progress = excluded.progress",
        (user_id, day, quest_id, after),
    )
    if before < quest.target <= after:
        progress.quests_completed.append(quest_id)


async def _achievement_values(conn: Conn, user_id: int) -> dict[str, int]:
    values = await repo.get_stats(conn, user_id)
    values["balance"] = await repo.get_balance(conn, user_id)
    return values


async def check_achievements(conn: Conn, user_id: int, now: int, progress: Progress | None = None) -> list[str]:
    """Идемпотентно выдаёт все выполненные достижения (INSERT OR IGNORE)."""
    values = await _achievement_values(conn, user_id)
    granted: list[str] = []
    for ach_id in ACHIEVEMENT_ORDER:
        ach = ACHIEVEMENTS[ach_id]
        if values.get(ach.stat, 0) >= ach.target:
            cur = await conn.execute(
                "INSERT OR IGNORE INTO user_achievements (user_id, achievement_id, earned_at) VALUES (?, ?, ?)",
                (user_id, ach_id, now),
            )
            if cur.rowcount == 1:
                granted.append(ach_id)
    if progress is not None:
        progress.achievements.extend(granted)
    return granted


async def achievement_statuses(conn: Conn, user_id: int) -> list[AchievementStatus]:
    values = await _achievement_values(conn, user_id)
    cur = await conn.execute("SELECT achievement_id, earned_at FROM user_achievements WHERE user_id = ?", (user_id,))
    earned = {r["achievement_id"]: int(r["earned_at"]) for r in await cur.fetchall()}
    result = []
    for ach_id in ACHIEVEMENT_ORDER:
        ach = ACHIEVEMENTS[ach_id]
        result.append(
            AchievementStatus(
                achievement_id=ach_id,
                earned=ach_id in earned,
                current=min(values.get(ach.stat, 0), ach.target),
                target=ach.target,
                earned_at=earned.get(ach_id),
            )
        )
    return result
