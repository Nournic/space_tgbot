"""Администрирование: /admin — сводная статистика. Доступно только ID из ADMIN_IDS."""

from __future__ import annotations

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.models import AdminStats
from app.services import Game

router = Router(name="admin")


def admin_stats_text(s: AdminStats) -> str:
    return (
        "📊 <b>Статистика сервера</b>\n\n"
        f"👥 Игроков: <b>{s.players}</b> (новых за сутки {s.new_24h}, активных {s.active_24h})\n"
        f"🏰 Кланов: {s.clans}\n\n"
        f"💰 На балансах: <b>{s.balances}</b> кр.\n"
        f"🔒 В ставках дуэлей: {s.escrow} кр.\n"
        f"🏦 В казнах кланов: {s.treasuries} кр.\n\n"
        f"📈 Начислено за сутки: {s.income_24h} кр. (без стартового капитала)\n"
        f"📉 Списано за сутки: {s.spent_24h} кр.\n\n"
        f"🤝 Активных P2P-предложений: {s.pending_offers}\n"
        f"⚔️ Ожидающих вызовов: {s.pending_duels}"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, game: Game, admin_ids: frozenset[int] = frozenset()) -> None:
    if message.from_user.id not in admin_ids:
        return  # для остальных команды как будто нет
    if message.chat.type != ChatType.PRIVATE:
        await message.reply("📊 /admin работает только в личке с ботом.")
        return
    await message.answer(admin_stats_text(await game.admin.stats()))
