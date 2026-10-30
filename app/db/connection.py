"""Управление подключениями SQLite.

Модель: отдельное соединение на каждую операцию. Мутации выполняются в
``BEGIN IMMEDIATE`` — SQLite сразу берёт RESERVED-блокировку, поэтому две
конкурентные операции сериализуются, а не перемежаются. Соединение никогда не
разделяется между задачами asyncio.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

log = logging.getLogger(__name__)

Conn = aiosqlite.Connection


class Database:
    def __init__(self, path: str, busy_timeout_ms: int = 15_000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    async def connect(self) -> Conn:
        conn = await aiosqlite.connect(self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        await conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    async def init(self) -> int:
        """Создаёт каталог, включает WAL, применяет миграции. Возвращает версию схемы."""
        from app.db.migrations import apply_migrations

        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        conn = await self.connect()
        try:
            cur = await conn.execute("PRAGMA journal_mode = WAL")
            mode = (await cur.fetchone())[0]
            log.info("SQLite journal_mode=%s", mode)
        finally:
            await conn.close()
        return await apply_migrations(self)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Conn]:
        """Пишущая транзакция BEGIN IMMEDIATE; ROLLBACK при любом исключении."""
        conn = await self.connect()
        try:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
            else:
                await conn.execute("COMMIT")
        finally:
            await conn.close()

    @asynccontextmanager
    async def read(self) -> AsyncIterator[Conn]:
        """Согласованное чтение в одной (deferred) транзакции."""
        conn = await self.connect()
        try:
            await conn.execute("BEGIN")
            try:
                yield conn
            finally:
                await conn.execute("ROLLBACK")
        finally:
            await conn.close()
