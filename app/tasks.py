"""Единственная фоновая задача: периодическая очистка просроченных вызовов/предложений/токенов.

Энергия восстанавливается лениво и задачи не требует. Сетевые вызовы Telegram
выполняются только после завершения транзакции очистки.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.services import Game

log = logging.getLogger(__name__)


async def notify_expired(bot: Bot, notices) -> None:
    for n in notices:
        if n.chat_id is None or n.message_id is None:
            continue
        try:
            await bot.edit_message_text(text=n.text, chat_id=n.chat_id, message_id=n.message_id, reply_markup=None)
        except TelegramAPIError as exc:
            log.debug("Не удалось обновить сообщение %s/%s: %s", n.chat_id, n.message_id, exc)


async def cleanup_loop(game: Game, bot: Bot, interval: int = 30) -> None:
    while True:
        try:
            notices = await game.cleanup()
            if notices:
                log.info("Закрыто просроченных объектов: %d", len(notices))
                await notify_expired(bot, notices)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка фоновой очистки")
        await asyncio.sleep(interval)
