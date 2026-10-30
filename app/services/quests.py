"""Ежедневные задания (UTC) и просмотр достижений."""

from __future__ import annotations

from app.clock import utc_date
from app.constants import QUEST_ORDER, QUESTS
from app.db import repositories as repo
from app.errors import GameError, StaleAction, ValidationError
from app.models import AchievementStatus, ClaimResult, Progress, QuestView
from app.services import progression
from app.services.base import ServiceContext


class QuestService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def today(self, user_id: int) -> tuple[str, list[QuestView]]:
        """Состояние заданий создаётся лениво: отсутствующая строка = прогресс 0."""
        async with self.ctx.db.read() as conn:
            day = utc_date(self.ctx.clock.now())
            await repo.require_user(conn, user_id)
            cur = await conn.execute(
                "SELECT quest_id, progress, claimed FROM user_quests WHERE user_id = ? AND quest_date = ?",
                (user_id, day),
            )
            rows = {r["quest_id"]: r for r in await cur.fetchall()}
        views = []
        for qid in QUEST_ORDER:
            row = rows.get(qid)
            target = QUESTS[qid].target
            views.append(
                QuestView(
                    qid, min(target, int(row["progress"])) if row else 0, target, bool(row["claimed"]) if row else False
                )
            )
        return day, views

    async def claim(self, user_id: int, quest_id: str, token: str | None = None) -> ClaimResult:
        quest_id = (quest_id or "").strip().lower()
        if quest_id not in QUESTS:
            raise ValidationError(f"❓ Неизвестное задание. Доступны: {', '.join(QUEST_ORDER)}.")
        quest = QUESTS[quest_id]
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            day = utc_date(now)
            if token is not None:
                payload = await repo.consume_token(conn, token, user_id, "quests", now)
                if payload.get("date") != day:  # кнопка вчерашнего дня
                    raise StaleAction()
            await repo.require_user(conn, user_id)
            cur = await conn.execute(
                "SELECT progress, claimed FROM user_quests WHERE user_id = ? AND quest_date = ? AND quest_id = ?",
                (user_id, day, quest_id),
            )
            row = await cur.fetchone()
            if row is None or int(row["progress"]) < quest.target:
                raise GameError("📋 Задание ещё не выполнено.")
            cur = await conn.execute(
                "UPDATE user_quests SET claimed = 1, claimed_at = ? "
                "WHERE user_id = ? AND quest_date = ? AND quest_id = ? AND claimed = 0",
                (now, user_id, day, quest_id),
            )
            if cur.rowcount != 1:
                raise GameError("✅ Награда за это задание уже получена.")
            progress = Progress()
            balance = await progression.earn(conn, user_id, quest.reward_credits, now)
            await repo.inc_stats(conn, user_id, quests_completed=1)
            await progression.add_xp(conn, user_id, quest.reward_xp, now, progress)
            await progression.check_achievements(conn, user_id, now, progress)
            await repo.add_ledger(conn, user_id, "quest_reward", quest.reward_credits, now, details=quest_id)
        return ClaimResult(quest_id, quest.reward_credits, quest.reward_xp, balance, progress)

    async def achievements(self, user_id: int) -> list[AchievementStatus]:
        async with self.ctx.db.read() as conn:
            await repo.require_user(conn, user_id)
            return await progression.achievement_statuses(conn, user_id)
