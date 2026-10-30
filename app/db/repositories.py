"""Низкоуровневые запросы. Все функции работают внутри уже открытой транзакции.

Только параметризованный SQL. Имена столбцов, подставляемые в текст запроса,
берутся из фиксированных белых списков (STAT_FIELDS, кулдауны), а не из ввода.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

import aiosqlite

from app.constants import ITEMS, STAT_FIELDS
from app.errors import InsufficientFunds, NotRegistered, NotYourButton, StaleAction, ValidationError

Conn = aiosqlite.Connection
Row = aiosqlite.Row


# --------------------------------------------------------------------------- пользователи
async def get_user(conn: Conn, user_id: int) -> Row | None:
    cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return await cur.fetchone()


async def require_user(conn: Conn, user_id: int) -> Row:
    row = await get_user(conn, user_id)
    if row is None:
        raise NotRegistered()
    return row


async def require_other_user(conn: Conn, user_id: int) -> Row:
    row = await get_user(conn, user_id)
    if row is None:
        raise ValidationError("🛰 Этот игрок ещё не зарегистрирован в игре.")
    return row


async def get_ship(conn: Conn, user_id: int) -> Row:
    cur = await conn.execute("SELECT * FROM ships WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotRegistered()
    return row


async def change_balance(conn: Conn, user_id: int, delta: int, now: int) -> int:
    """Атомарно меняет баланс; не допускает ухода в минус. Возвращает новый баланс."""
    cur = await conn.execute(
        "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ? AND balance + ? >= 0",
        (delta, now, user_id, delta),
    )
    if cur.rowcount != 1:
        row = await get_user(conn, user_id)
        if row is None:
            raise NotRegistered()
        raise InsufficientFunds(f"💸 Недостаточно кредитов: нужно {-delta}, на счету {row['balance']}.")
    cur = await conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    return int((await cur.fetchone())[0])


async def get_balance(conn: Conn, user_id: int) -> int:
    cur = await conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotRegistered()
    return int(row[0])


# --------------------------------------------------------------------------- инвентарь
async def get_inventory(conn: Conn, user_id: int) -> dict[str, int]:
    cur = await conn.execute("SELECT item_id, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,))
    return {r["item_id"]: int(r["quantity"]) for r in await cur.fetchall()}


async def get_reserved(conn: Conn, user_id: int, now: int) -> dict[str, int]:
    """Логический резерв активных (не истёкших по времени) P2P-предложений продавца."""
    cur = await conn.execute(
        "SELECT item_id, SUM(quantity) AS q FROM trade_offers "
        "WHERE seller_id = ? AND status = 'pending' AND expires_at > ? GROUP BY item_id",
        (user_id, now),
    )
    return {r["item_id"]: int(r["q"]) for r in await cur.fetchall()}


def cargo_used(inventory: dict[str, int]) -> int:
    return sum(qty * ITEMS[item].weight for item, qty in inventory.items())


async def available_quantity(conn: Conn, user_id: int, item_id: str, now: int) -> int:
    inv = await get_inventory(conn, user_id)
    reserved = await get_reserved(conn, user_id, now)
    return inv.get(item_id, 0) - reserved.get(item_id, 0)


async def add_item(conn: Conn, user_id: int, item_id: str, qty: int) -> None:
    if qty <= 0:
        raise ValueError("qty must be positive")
    await conn.execute(
        "INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
        (user_id, item_id, qty),
    )


async def remove_item(conn: Conn, user_id: int, item_id: str, qty: int) -> None:
    if qty <= 0:
        raise ValueError("qty must be positive")
    cur = await conn.execute(
        "UPDATE inventory SET quantity = quantity - ? WHERE user_id = ? AND item_id = ? AND quantity >= ?",
        (qty, user_id, item_id, qty),
    )
    if cur.rowcount != 1:
        raise ValidationError(f"📦 Недостаточно товара «{ITEMS[item_id].title}».")
    await conn.execute("DELETE FROM inventory WHERE user_id = ? AND item_id = ? AND quantity = 0", (user_id, item_id))


# --------------------------------------------------------------------------- статистика/журнал
async def inc_stats(conn: Conn, user_id: int, **fields: int) -> None:
    parts = []
    values: list[int] = []
    for name, value in fields.items():
        if name not in STAT_FIELDS:
            raise ValueError(f"unknown stat {name}")
        if value:
            parts.append(f"{name} = {name} + ?")
            values.append(int(value))
    if not parts:
        return
    await conn.execute(f"UPDATE player_stats SET {', '.join(parts)} WHERE user_id = ?", (*values, user_id))


async def get_stats(conn: Conn, user_id: int) -> dict[str, int]:
    cur = await conn.execute("SELECT * FROM player_stats WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotRegistered()
    return {k: int(row[k]) for k in STAT_FIELDS}


async def add_ledger(
    conn: Conn,
    user_id: int,
    kind: str,
    amount: int,
    now: int,
    *,
    item_id: str | None = None,
    quantity: int | None = None,
    counterparty_id: int | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    details: str | None = None,
) -> None:
    balance = await get_balance(conn, user_id)
    await conn.execute(
        "INSERT INTO ledger (user_id, kind, amount, balance_after, item_id, quantity, counterparty_id, "
        "ref_type, ref_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, amount, balance, item_id, quantity, counterparty_id, ref_type, ref_id, details, now),
    )


# --------------------------------------------------------------------------- кланы
async def get_member_clan_id(conn: Conn, user_id: int) -> int | None:
    cur = await conn.execute("SELECT clan_id FROM clan_members WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    return int(row[0]) if row else None


# --------------------------------------------------------------------------- одноразовые токены
async def create_token(
    conn: Conn, user_id: int, chat_id: int | None, action: str, payload: dict[str, Any], now: int, ttl: int
) -> str:
    token = secrets.token_hex(6)
    await conn.execute(
        "INSERT INTO action_tokens (token, user_id, chat_id, action, payload, status, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
        (token, user_id, chat_id, action, json.dumps(payload, ensure_ascii=False), now, now + ttl),
    )
    return token


async def consume_token(conn: Conn, token: str, user_id: int, action: str, now: int) -> dict[str, Any]:
    """Проверяет владельца/свежесть и атомарно помечает токен использованным.

    Вызывается в той же транзакции, что и само действие: если действие
    откатится, токен останется активным; если успешно — повтор невозможен.
    """
    cur = await conn.execute("SELECT * FROM action_tokens WHERE token = ?", (token,))
    row = await cur.fetchone()
    if row is None or row["action"] != action:
        raise StaleAction()
    if int(row["user_id"]) != user_id:
        raise NotYourButton()
    if row["status"] != "active" or int(row["expires_at"]) <= now:
        raise StaleAction()
    cur = await conn.execute(
        "UPDATE action_tokens SET status = 'used', used_at = ? WHERE token = ? AND status = 'active'",
        (now, token),
    )
    if cur.rowcount != 1:
        raise StaleAction()
    return json.loads(row["payload"])
