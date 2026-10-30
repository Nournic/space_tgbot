"""Кланы. Единственный источник истины о членстве — таблица clan_members.

Создание стоит 1 000 кредитов (сгорают). Казна пополняется взносами и при
роспуске сгорает без возврата. Лидер не может выйти без передачи лидерства.
"""

from __future__ import annotations

import re

from app.constants import CLAN_CREATE_COST, CLAN_MAX_MEMBERS, CLAN_NAME_MAX, CLAN_NAME_MIN, CLAN_PAGE_SIZE, MAX_DONATE
from app.db import repositories as repo
from app.db.connection import Conn
from app.errors import GameError, StaleAction, ValidationError
from app.models import ClanView
from app.services.base import ServiceContext

_NAME_RE = re.compile(r"^[\w .\-]+$", re.UNICODE)


def normalize_clan_name(raw: str | None) -> tuple[str, str]:
    name = " ".join((raw or "").split())
    if not (CLAN_NAME_MIN <= len(name) <= CLAN_NAME_MAX):
        raise ValidationError(f"🏷 Название клана — от {CLAN_NAME_MIN} до {CLAN_NAME_MAX} символов.")
    if not _NAME_RE.match(name):
        raise ValidationError("🏷 Допустимы буквы, цифры, пробел, точка, дефис и подчёркивание.")
    return name, name.casefold()


async def _clan_view(conn: Conn, clan_id: int, with_members: bool = False) -> ClanView:
    cur = await conn.execute(
        "SELECT c.*, u.display_name AS leader_name, "
        "(SELECT COUNT(*) FROM clan_members m WHERE m.clan_id = c.id) AS members "
        "FROM clans c JOIN users u ON u.user_id = c.leader_id WHERE c.id = ?",
        (clan_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise GameError("🏰 Клан не найден.")
    view = ClanView(
        int(row["id"]),
        row["name"],
        int(row["leader_id"]),
        row["leader_name"],
        int(row["treasury"]),
        bool(row["is_open"]),
        int(row["members"]),
        int(row["created_at"]),
    )
    if with_members:
        cur = await conn.execute(
            "SELECT m.user_id, u.display_name FROM clan_members m JOIN users u ON u.user_id = m.user_id "
            "WHERE m.clan_id = ? ORDER BY m.joined_at, m.user_id",
            (clan_id,),
        )
        view.members = [(int(r[0]), r[1]) for r in await cur.fetchall()]
    return view


class ClanService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def create(self, user_id: int, raw_name: str) -> ClanView:
        name, key = normalize_clan_name(raw_name)
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            await repo.require_user(conn, user_id)
            if await repo.get_member_clan_id(conn, user_id) is not None:
                raise GameError("🏰 Вы уже состоите в клане.")
            cur = await conn.execute("SELECT 1 FROM clans WHERE name_key = ?", (key,))
            if await cur.fetchone():
                raise GameError("🏷 Клан с таким названием уже существует.")
            await repo.change_balance(conn, user_id, -CLAN_CREATE_COST, now)
            cur = await conn.execute(
                "INSERT INTO clans (name, name_key, leader_id, treasury, is_open, created_at) "
                "VALUES (?, ?, ?, 0, 1, ?)",
                (name, key, user_id, now),
            )
            clan_id = int(cur.lastrowid)
            await conn.execute(
                "INSERT INTO clan_members (user_id, clan_id, joined_at) VALUES (?, ?, ?)", (user_id, clan_id, now)
            )
            await repo.add_ledger(
                conn, user_id, "clan_create", -CLAN_CREATE_COST, now, ref_type="clan", ref_id=clan_id, details=name
            )
            view = await _clan_view(conn, clan_id)
        return view

    async def list_open(self, page: int = 0) -> tuple[list[ClanView], int, int]:
        async with self.ctx.db.read() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM clans WHERE is_open = 1")
            total = int((await cur.fetchone())[0])
            pages = max(1, -(-total // CLAN_PAGE_SIZE))
            page = max(0, min(page, pages - 1))
            cur = await conn.execute(
                "SELECT id FROM clans WHERE is_open = 1 ORDER BY id LIMIT ? OFFSET ?",
                (CLAN_PAGE_SIZE, page * CLAN_PAGE_SIZE),
            )
            ids = [int(r[0]) for r in await cur.fetchall()]
            views = [await _clan_view(conn, cid) for cid in ids]
        return views, page, pages

    async def join(self, user_id: int, clan_id: int) -> ClanView:
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            await repo.require_user(conn, user_id)
            if await repo.get_member_clan_id(conn, user_id) is not None:
                raise GameError("🏰 Вы уже состоите в клане. Сначала /clan leave.")
            cur = await conn.execute("SELECT is_open FROM clans WHERE id = ?", (clan_id,))
            row = await cur.fetchone()
            if row is None:
                raise GameError("🏰 Клан не найден.")
            if not row[0]:
                raise GameError("🔒 Клан закрыт для вступления.")
            cur = await conn.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = ?", (clan_id,))
            if int((await cur.fetchone())[0]) >= CLAN_MAX_MEMBERS:
                raise GameError(f"👥 В клане уже максимум участников ({CLAN_MAX_MEMBERS}).")
            await conn.execute(
                "INSERT INTO clan_members (user_id, clan_id, joined_at) VALUES (?, ?, ?)", (user_id, clan_id, now)
            )
            view = await _clan_view(conn, clan_id)
        return view

    async def leave(self, user_id: int) -> str:
        async with self.ctx.db.transaction() as conn:
            await repo.require_user(conn, user_id)
            clan_id = await repo.get_member_clan_id(conn, user_id)
            if clan_id is None:
                raise GameError("🏰 Вы не состоите в клане.")
            view = await _clan_view(conn, clan_id)
            if view.leader_id == user_id:
                raise GameError(
                    "👑 Лидер не может выйти. Передайте лидерство (/clan transfer ответом на "
                    "сообщение участника) или распустите клан (/clan disband)."
                )
            await conn.execute("DELETE FROM clan_members WHERE user_id = ?", (user_id,))
        return view.name

    async def info(self, user_id: int, clan_id: int | None = None) -> ClanView:
        async with self.ctx.db.read() as conn:
            if clan_id is None:
                await repo.require_user(conn, user_id)
                clan_id = await repo.get_member_clan_id(conn, user_id)
                if clan_id is None:
                    raise GameError("🏰 Вы не состоите в клане. Смотрите /clan list.")
            return await _clan_view(conn, clan_id, with_members=True)

    async def my_clan_id(self, user_id: int) -> int | None:
        async with self.ctx.db.read() as conn:
            return await repo.get_member_clan_id(conn, user_id)

    async def donate(self, user_id: int, amount: int) -> tuple[ClanView, int]:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1 or amount > MAX_DONATE:
            raise ValidationError(f"💰 Сумма взноса — целое число от 1 до {MAX_DONATE}.")
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            await repo.require_user(conn, user_id)
            clan_id = await repo.get_member_clan_id(conn, user_id)
            if clan_id is None:
                raise GameError("🏰 Вы не состоите в клане.")
            balance = await repo.change_balance(conn, user_id, -amount, now)
            await conn.execute("UPDATE clans SET treasury = treasury + ? WHERE id = ?", (amount, clan_id))
            await repo.add_ledger(conn, user_id, "clan_donate", -amount, now, ref_type="clan", ref_id=clan_id)
            view = await _clan_view(conn, clan_id)
        return view, balance

    async def transfer(self, user_id: int, new_leader_id: int) -> ClanView:
        async with self.ctx.db.transaction() as conn:
            await repo.require_user(conn, user_id)
            clan_id = await repo.get_member_clan_id(conn, user_id)
            if clan_id is None:
                raise GameError("🏰 Вы не состоите в клане.")
            view = await _clan_view(conn, clan_id)
            if view.leader_id != user_id:
                raise GameError("👑 Передать лидерство может только лидер клана.")
            if new_leader_id == user_id:
                raise GameError("👑 Вы уже лидер.")
            if await repo.get_member_clan_id(conn, new_leader_id) != clan_id:
                raise GameError("👥 Этот игрок не состоит в вашем клане.")
            cur = await conn.execute(
                "UPDATE clans SET leader_id = ? WHERE id = ? AND leader_id = ?", (new_leader_id, clan_id, user_id)
            )
            if cur.rowcount != 1:
                raise StaleAction()
            view = await _clan_view(conn, clan_id)
        return view

    async def leader_clan(self, user_id: int) -> ClanView:
        async with self.ctx.db.read() as conn:
            await repo.require_user(conn, user_id)
            clan_id = await repo.get_member_clan_id(conn, user_id)
            if clan_id is None:
                raise GameError("🏰 Вы не состоите в клане.")
            view = await _clan_view(conn, clan_id)
        if view.leader_id != user_id:
            raise GameError("👑 Распустить клан может только лидер.")
        return view

    async def disband(self, user_id: int, token: str | None = None) -> ClanView:
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            payload = {}
            if token is not None:
                payload = await repo.consume_token(conn, token, user_id, "clan_disband", now)
            clan_id = await repo.get_member_clan_id(conn, user_id)
            if clan_id is None:
                raise GameError("🏰 Вы не состоите в клане.")
            if token is not None and payload.get("clan_id") != clan_id:
                raise StaleAction()
            view = await _clan_view(conn, clan_id)
            if view.leader_id != user_id:
                raise GameError("👑 Распустить клан может только лидер.")
            await repo.add_ledger(
                conn,
                user_id,
                "clan_disband",
                0,
                now,
                ref_type="clan",
                ref_id=clan_id,
                details=f"{view.name}: сгорело {view.treasury}",
            )
            await conn.execute("DELETE FROM clans WHERE id = ?", (clan_id,))  # участники — ON DELETE CASCADE
        return view
