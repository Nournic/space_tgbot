"""Глобальные мировые события: одно на календарные сутки UTC, стабильно по дате и seed."""

from __future__ import annotations

import hashlib

from app.clock import utc_date
from app.constants import EVENT_ORDER, WORLD_EVENTS, WorldEvent


def stable_int(*parts: str) -> int:
    """Стабильный между процессами хеш (в отличие от встроенного hash())."""
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def event_for_date(day: str, seed: str) -> WorldEvent:
    return WORLD_EVENTS[EVENT_ORDER[stable_int(seed, "event", day) % len(EVENT_ORDER)]]


class EventService:
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    def current(self) -> tuple[str, WorldEvent]:
        day = utc_date(self.ctx.clock.now())
        return day, event_for_date(day, self.ctx.seed)
