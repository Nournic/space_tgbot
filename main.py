"""Точка входа: python main.py"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from app.bot.routers import bot_commands, setup_dispatcher
from app.db.connection import Database
from app.services import build_game
from app.tasks import cleanup_loop, notify_expired
from config import load_settings


class _TokenFilter(logging.Filter):
    """Маскирует токен бота, если он случайно попадёт в лог (например, в URL запроса)."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if self.token:
            message = record.getMessage()
            if self.token in message:
                record.msg = message.replace(self.token, "***")
                record.args = None
        return True


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(_TokenFilter(settings.bot_token))
    log = logging.getLogger("space_trader")

    db = Database(settings.database_path)
    version = await db.init()
    log.info("База данных %s готова, версия схемы %s", settings.database_path, version)

    game = build_game(db, seed=settings.game_seed)
    # При старте сразу закрываем всё, что истекло, пока бот был выключен (с возвратом ставок).
    expired = await game.cleanup()
    if expired:
        log.info("При старте закрыто просроченных объектов: %d", len(expired))

    bot = Bot(
        settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    )
    dp = setup_dispatcher(game)
    cleanup = asyncio.create_task(cleanup_loop(game, bot))
    try:
        try:
            await bot.set_my_commands(bot_commands())
        except TelegramAPIError as exc:
            log.warning("Не удалось зарегистрировать список команд: %s", exc)
        # Сообщения закрытых при старте предложений и вызовов: убираем кнопки и показываем итог.
        await notify_expired(bot, expired, game.ctx.clock.now())
        log.info("Бот запущен (long polling)")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        cleanup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup
        await bot.session.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
