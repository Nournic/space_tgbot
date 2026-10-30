"""Middleware: перевод игровых ошибок в понятные ответы и обновление имени игрока."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, TelegramObject

from app.bot.utils import alert_text, cb_answer, display_name
from app.errors import GameError
from app.services import Game

log = logging.getLogger(__name__)

INTERNAL_ERROR = "⚠️ Внутренняя ошибка. Попробуйте позже."


class GameMiddleware(BaseMiddleware):
    """Экземпляр Game берётся из workflow data (data["game"])."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        game: Game | None = data.get("game")
        user = getattr(event, "from_user", None)
        if game is not None and user is not None and not user.is_bot:
            try:
                await game.accounts.touch_name(user.id, display_name(user))
            except Exception:
                log.exception("touch_name failed")
        try:
            return await handler(event, data)
        except GameError as exc:
            await self._report(event, exc.message, alert=True)
        except TelegramAPIError as exc:
            log.warning("Telegram API error: %s", exc)
        except Exception:
            log.exception("Unhandled error while processing update")
            await self._report(event, INTERNAL_ERROR, alert=True)
        return None

    @staticmethod
    async def _report(event: TelegramObject, text: str, alert: bool) -> None:
        try:
            if isinstance(event, Message):
                # Ответом на команду: в группе видно, чья это ошибка.
                await event.reply(text)
            else:  # CallbackQuery: ответ всплывающим уведомлением
                await cb_answer(event, alert_text(text), alert=alert)
        except TelegramAPIError as exc:
            log.debug("error report failed: %s", exc)
