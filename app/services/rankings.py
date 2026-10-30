"""Глобальные рейтинги: топ-10 + место текущего игрока. Сортировка устойчива по ID."""
from __future__ import annotations

from app.constants import TOP_LIMIT
from app.models import RankRow, Ranking
from app.services.base import ServiceContext

# Выражения — фиксированный белый список, не пользовательский ввод.
_PLAYER_CATEGORIES = {
    "balance": ("users u", "u.balance"),
    "xp": ("users u", "u.xp"),
    "pve": ("users u JOIN player_stats s ON s.user_id = u.user_id", "s.pve_wins"),
    "pvp": ("users u JOIN player_stats s ON s.user_id = u.user_id", "s.pvp_wins"),
}
CATEGORIES = ("balance", "xp", "pve", "pvp", "clans")


class RankingService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def top(self, category: str, user_id: int) -> Ranking:
        if category not in CATEGORIES:
            category = "balance"
        if category == "clans":
            return await self._clans(user_id)
        source, expr = _PLAYER_CATEGORIES[category]
        async with self.ctx.db.read() as conn:
            cur = await conn.execute(
                f"SELECT u.user_id, u.display_name, {expr} AS value, u.level FROM {source} "
                f"ORDER BY value DESC, u.user_id ASC LIMIT ?", (TOP_LIMIT,))
            rows = [RankRow(i + 1, int(r[0]), r[1], int(r[2]), f"ур. {r[3]}") for i, r in
                    enumerate(await cur.fetchall())]
            me = None
            if all(r.entity_id != user_id for r in rows):
                cur = await conn.execute(
                    f"SELECT u.user_id, u.display_name, {expr} AS value, u.level FROM {source} WHERE u.user_id = ?",
                    (user_id,))
                mine = await cur.fetchone()
                if mine is not None:
                    value = int(mine[2])
                    cur = await conn.execute(
                        f"SELECT COUNT(*) FROM {source} WHERE {expr} > ? OR ({expr} = ? AND u.user_id < ?)",
                        (value, value, user_id))
                    place = int((await cur.fetchone())[0]) + 1
                    me = RankRow(place, user_id, mine[1], value, f"ур. {mine[3]}")
        return Ranking(category, rows, me)

    async def _clans(self, user_id: int) -> Ranking:
        sql = ("SELECT c.id, c.name, c.treasury, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id = c.id) "
               "FROM clans c")
        async with self.ctx.db.read() as conn:
            cur = await conn.execute(f"{sql} ORDER BY c.treasury DESC, c.id ASC LIMIT ?", (TOP_LIMIT,))
            rows = [RankRow(i + 1, int(r[0]), r[1], int(r[2]), f"👥 {r[3]}") for i, r in
                    enumerate(await cur.fetchall())]
            me = None
            cur = await conn.execute("SELECT clan_id FROM clan_members WHERE user_id = ?", (user_id,))
            mine = await cur.fetchone()
            if mine is not None and all(r.entity_id != int(mine[0]) for r in rows):
                clan_id = int(mine[0])
                cur = await conn.execute(f"{sql} WHERE c.id = ?", (clan_id,))
                c = await cur.fetchone()
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM clans WHERE treasury > ? OR (treasury = ? AND id < ?)",
                    (int(c[2]), int(c[2]), clan_id))
                me = RankRow(int((await cur.fetchone())[0]) + 1, clan_id, c[1], int(c[2]), f"👥 {c[3]}")
        return Ranking("clans", rows, me)
