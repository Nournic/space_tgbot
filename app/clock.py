"""Источник времени (подменяется в тестах). Все timestamps — целые UNIX-секунды UTC."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> int: ...


class SystemClock:
    def now(self) -> int:
        return int(time.time())


class FixedClock:
    """Управляемые часы для тестов."""

    def __init__(self, start: int) -> None:
        self.current = start

    def now(self) -> int:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += seconds


def utc_date(ts: int) -> str:
    """Календарная дата UTC в формате YYYY-MM-DD — не зависит от часового пояса машины."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def format_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
