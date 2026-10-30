"""Антифлуд: лишние команды и нажатия одного игрока отбрасываются до обращения к игре."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from app.bot.utils import cb_answer
from app.constants import FLOOD_MAX_ACTIONS, FLOOD_WINDOW_SECONDS

TOO_FAST = "🐢 Слишком часто. Подождите несколько секунд."


class Throttle:
    """Скользящее окно: не больше ``limit`` событий игрока за ``window`` секунд.

    Состояние живёт в памяти процесса: после перезапуска счётчики обнуляются, и это нормально.
    """

    def __init__(
        self,
        limit: int = FLOOD_MAX_ACTIONS,
        window: float = FLOOD_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._events: dict[int, deque[float]] = {}

    def allow(self, user_id: int) -> bool:
        now = self.clock()
        events = self._events.setdefault(user_id, deque())
        while events and events[0] <= now - self.window:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        if len(self._events) > 10_000:  # не копим тех, кто давно молчит
            self._events = {uid: ev for uid, ev in self._events.items() if ev and ev[-1] > now - self.window}
        return True


class ThrottleMiddleware(BaseMiddleware):
    """Отбрасывает слишком частые команды и нажатия. Throttle берётся из data["throttle"].

    Middleware внутреннее, поэтому считаются только апдейты, дошедшие до хендлера бота,
    а не обычная переписка в группе.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        throttle: Throttle | None = data.get("throttle")
        user = getattr(event, "from_user", None)
        if throttle is None or user is None or throttle.allow(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await cb_answer(event, TOO_FAST)
        return None  # лишние команды молча игнорируем: ответ сам добавил бы флуда
