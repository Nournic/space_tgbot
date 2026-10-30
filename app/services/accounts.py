"""Регистрация, профиль, инвентарь, история операций и одноразовые токены."""

from __future__ import annotations

import json
from typing import Any

from app.constants import (
    DISPLAY_NAME_MAX,
    HISTORY_PAGE_SIZE,
    MAX_ENERGY,
    SHIP_CLASSES,
    START_BALANCE,
    START_PLANET,
    START_SHIP,
    TOKEN_TTL,
)
from app.db import repositories as repo
from app.errors import NotYourButton, StaleAction
from app.models import HistoryPage, LedgerEntry, Profile, RegisterResult
from app.services.base import ServiceContext, load_ship


def clean_name(name: str | None, user_id: int) -> str:
    text = " ".join((name or "").split())
    text = "".join(ch for ch in text if ch.isprintable())
    text = text[:DISPLAY_NAME_MAX].strip()
    return text or f"Пилот {user_id}"


class AccountService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def register(self, user_id: int, name: str | None) -> RegisterResult:
        """Идемпотентная регистрация: все стартовые записи — одна транзакция."""
        display = clean_name(name, user_id)
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            existing = await repo.get_user(conn, user_id)
            created = existing is None
            if created:
                await conn.execute(
                    "INSERT INTO users (user_id, display_name, balance, planet_id, xp, level, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 0, 1, ?, ?)",
                    (user_id, display, START_BALANCE, START_PLANET, now, now),
                )
                await conn.execute(
                    "INSERT INTO ships (user_id, ship_class, hp, energy, energy_updated_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, START_SHIP, SHIP_CLASSES[START_SHIP].hp, MAX_ENERGY, now, now, now),
                )
                await conn.execute("INSERT INTO player_stats (user_id) VALUES (?)", (user_id,))
                await repo.add_ledger(conn, user_id, "register", START_BALANCE, now, details="Стартовый капитал")
            elif existing["display_name"] != display:
                await conn.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display, user_id))
        return RegisterResult(created=created, profile=await self.profile(user_id))

    async def touch_name(self, user_id: int, name: str | None) -> None:
        """Обновляет отображаемое имя зарегистрированного игрока, если оно изменилось."""
        display = clean_name(name, user_id)
        async with self.ctx.db.read() as conn:
            row = await repo.get_user(conn, user_id)
        if row is None or row["display_name"] == display:
            return
        async with self.ctx.db.transaction() as conn:
            await conn.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display, user_id))

    async def is_registered(self, user_id: int) -> bool:
        async with self.ctx.db.read() as conn:
            return await repo.get_user(conn, user_id) is not None

    async def profile(self, user_id: int) -> Profile:
        async with self.ctx.db.read() as conn:
            now = self.ctx.clock.now()
            user = await repo.require_user(conn, user_id)
            ship = await load_ship(conn, user_id, now)
            inventory = await repo.get_inventory(conn, user_id)
            reserved = await repo.get_reserved(conn, user_id, now)
            stats = await repo.get_stats(conn, user_id)
            cur = await conn.execute(
                "SELECT c.name FROM clan_members m JOIN clans c ON c.id = m.clan_id WHERE m.user_id = ?", (user_id,)
            )
            clan = await cur.fetchone()
        return Profile(
            user_id=user_id,
            display_name=user["display_name"],
            balance=int(user["balance"]),
            planet_id=user["planet_id"],
            xp=int(user["xp"]),
            level=int(user["level"]),
            ship=ship,
            inventory=inventory,
            reserved=reserved,
            cargo_used=repo.cargo_used(inventory),
            clan_name=clan["name"] if clan else None,
            stats=stats,
            created_at=int(user["created_at"]),
        )

    async def history(self, user_id: int, page: int = 0) -> HistoryPage:
        async with self.ctx.db.read() as conn:
            await repo.require_user(conn, user_id)
            cur = await conn.execute("SELECT COUNT(*) FROM ledger WHERE user_id = ?", (user_id,))
            total = int((await cur.fetchone())[0])
            pages = max(1, -(-total // HISTORY_PAGE_SIZE))
            page = max(0, min(page, pages - 1))
            cur = await conn.execute(
                "SELECT id, kind, amount, balance_after, item_id, quantity, details, created_at FROM ledger "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, HISTORY_PAGE_SIZE, page * HISTORY_PAGE_SIZE),
            )
            rows = await cur.fetchall()
        entries = [
            LedgerEntry(
                int(r["id"]),
                r["kind"],
                int(r["amount"]),
                int(r["balance_after"]),
                r["item_id"],
                None if r["quantity"] is None else int(r["quantity"]),
                r["details"],
                int(r["created_at"]),
            )
            for r in rows
        ]
        return HistoryPage(entries=entries, page=page, pages=pages, total=total)


class TokenService:
    """Одноразовые токены для inline-кнопок, изменяющих состояние."""

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def issue(
        self,
        user_id: int,
        chat_id: int | None,
        action: str,
        payload: dict[str, Any] | None = None,
        ttl: int = TOKEN_TTL,
    ) -> str:
        async with self.ctx.db.transaction() as conn:
            return await repo.create_token(conn, user_id, chat_id, action, payload or {}, self.ctx.clock.now(), ttl)

    async def discard(self, token: str, user_id: int, action: str) -> None:
        """Погашает токен без действия (кнопка «Отмена»)."""
        async with self.ctx.db.transaction() as conn:
            await repo.consume_token(conn, token, user_id, action, self.ctx.clock.now())

    async def peek(self, token: str, user_id: int) -> tuple[str, dict[str, Any]]:
        """Определяет тип действия для маршрутизации; не расходует токен."""
        async with self.ctx.db.read() as conn:
            cur = await conn.execute("SELECT * FROM action_tokens WHERE token = ?", (token,))
            row = await cur.fetchone()
        if row is None:
            raise StaleAction()
        if int(row["user_id"]) != user_id:
            raise NotYourButton()
        if row["status"] != "active" or int(row["expires_at"]) <= self.ctx.clock.now():
            raise StaleAction()
        return row["action"], json.loads(row["payload"])
