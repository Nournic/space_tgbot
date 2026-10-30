"""Единственная фоновая задача: периодическая очистка просроченных вызовов/предложений/токенов.

Энергия восстанавливается лениво и задачи не требует. Сетевые вызовы Telegram
выполняются только после завершения транзакции очистки.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.bot.formatting import challenge_text, offer_text
from app.models import ChallengeView, ExpiredNotice, OfferView
from app.services import Game

log = logging.getLogger(__name__)


def notice_text(notice: ExpiredNotice, now: int) -> str:
    """Полный текст предложения или вызова со статусом «истекло», чтобы было видно, что истекло."""
    if isinstance(notice.view, OfferView):
        return offer_text(notice.view, now)
    if isinstance(notice.view, ChallengeView):
        return challenge_text(notice.view, now)
    return notice.text


async def notify_expired(bot: Bot, notices: list[ExpiredNotice], now: int) -> None:
    for n in notices:
        if n.chat_id is None or n.message_id is None:
            continue
        try:
            await bot.edit_message_text(
                text=notice_text(n, now), chat_id=n.chat_id, message_id=n.message_id, reply_markup=None
            )
        except TelegramAPIError as exc:
            log.debug("Не удалось обновить сообщение %s/%s: %s", n.chat_id, n.message_id, exc)


async def cleanup_loop(game: Game, bot: Bot, interval: int = 30) -> None:
    while True:
        try:
            notices = await game.cleanup()
            if notices:
                log.info("Закрыто просроченных объектов: %d", len(notices))
                await notify_expired(bot, notices, game.ctx.clock.now())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка фоновой очистки")
        await asyncio.sleep(interval)
