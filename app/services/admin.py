"""Сводная статистика для администраторов. Только чтение."""

from __future__ import annotations

from app.models import AdminStats
from app.services.base import ServiceContext

DAY = 86_400


class AdminService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def stats(self) -> AdminStats:
        async with self.ctx.db.read() as conn:
            now = self.ctx.clock.now()
            since = now - DAY

            async def scalar(sql: str, params: tuple = ()) -> int:
                cur = await conn.execute(sql, params)
                return int((await cur.fetchone())[0] or 0)

            players = await scalar("SELECT COUNT(*) FROM users")
            new_24h = await scalar("SELECT COUNT(*) FROM users WHERE created_at >= ?", (since,))
            # Перелёт и добыча меняют только ships, сделки — users: активен тот, у кого изменилось хоть что-то.
            active_24h = await scalar(
                "SELECT COUNT(*) FROM users u JOIN ships s ON s.user_id = u.user_id "
                "WHERE u.updated_at >= ? OR s.updated_at >= ?",
                (since, since),
            )
            balances = await scalar("SELECT SUM(balance) FROM users")
            escrow = await scalar("SELECT SUM(stake) FROM pvp_challenges WHERE status = 'pending'")
            treasuries = await scalar("SELECT SUM(treasury) FROM clans")
            income_24h = await scalar(
                "SELECT SUM(amount) FROM ledger WHERE created_at >= ? AND amount > 0 AND kind <> 'register'", (since,)
            )
            spent_24h = await scalar("SELECT -SUM(amount) FROM ledger WHERE created_at >= ? AND amount < 0", (since,))
            pending_offers = await scalar("SELECT COUNT(*) FROM trade_offers WHERE status = 'pending'")
            pending_duels = await scalar("SELECT COUNT(*) FROM pvp_challenges WHERE status = 'pending'")
            clans = await scalar("SELECT COUNT(*) FROM clans")
        return AdminStats(
            players=players,
            new_24h=new_24h,
            active_24h=active_24h,
            balances=balances,
            escrow=escrow,
            treasuries=treasuries,
            income_24h=income_24h,
            spent_24h=spent_24h,
            pending_offers=pending_offers,
            pending_duels=pending_duels,
            clans=clans,
        )
