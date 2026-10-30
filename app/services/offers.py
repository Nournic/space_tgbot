"""P2P-предложения с логическим резервом товара.

Товар остаётся в inventory продавца (и занимает его трюм), но
available = total − SUM(qty активных предложений) уменьшается. Принятие:
статус переводится в 'accepted' условным UPDATE (снимая резерв), затем в той
же транзакции товар списывается у продавца и зачисляется покупателю, деньги
переходят от покупателя к продавцу. P2P не создаёт и не уничтожает кредиты.
"""
from __future__ import annotations

from app.constants import ITEMS, MAX_PRICE, OFFER_TTL
from app.db import repositories as repo
from app.db.connection import Conn
from app.errors import GameError, NotYourButton, StaleAction, ValidationError
from app.models import ExpiredNotice, OfferOutcome, OfferView, Progress, ship_capacity
from app.services import progression
from app.services.base import ServiceContext
from app.services.economy import validate_item, validate_qty

_SELECT = (
    "SELECT o.*, su.display_name AS seller_name, bu.display_name AS buyer_name "
    "FROM trade_offers o JOIN users su ON su.user_id = o.seller_id JOIN users bu ON bu.user_id = o.buyer_id"
)


def _view(row) -> OfferView:
    return OfferView(
        id=int(row["id"]), seller_id=int(row["seller_id"]), seller_name=row["seller_name"],
        buyer_id=int(row["buyer_id"]), buyer_name=row["buyer_name"], item_id=row["item_id"],
        quantity=int(row["quantity"]), price=int(row["price"]), status=row["status"],
        created_at=int(row["created_at"]), expires_at=int(row["expires_at"]),
        chat_id=row["chat_id"], message_id=row["message_id"],
    )


async def _get(conn: Conn, offer_id: int):
    cur = await conn.execute(f"{_SELECT} WHERE o.id = ?", (offer_id,))
    row = await cur.fetchone()
    if row is None:
        raise StaleAction()
    return row


async def _set_status(conn: Conn, offer_id: int, status: str, now: int) -> bool:
    cur = await conn.execute(
        "UPDATE trade_offers SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
        (status, now, offer_id),
    )
    return cur.rowcount == 1


class OfferService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def create(self, seller_id: int, buyer_id: int, item_id: str, qty: int, price: int,
                     chat_id: int | None) -> OfferView:
        item_id = validate_item(item_id)
        validate_qty(qty)
        if isinstance(price, bool) or not isinstance(price, int) or price < 0 or price > MAX_PRICE:
            raise ValidationError(f"💰 Цена — целое число от 0 до {MAX_PRICE}.")
        if seller_id == buyer_id:
            raise ValidationError("🤨 Нельзя заключить сделку с самим собой.")
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            await repo.require_user(conn, seller_id)
            await repo.require_other_user(conn, buyer_id)
            available = await repo.available_quantity(conn, seller_id, item_id, now)
            if available < qty:
                raise GameError(f"📦 Доступно только {max(0, available)} × {ITEMS[item_id].title} "
                                "(с учётом резерва других предложений).")
            cur = await conn.execute(
                "INSERT INTO trade_offers (seller_id, buyer_id, item_id, quantity, price, status, chat_id, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (seller_id, buyer_id, item_id, qty, price, chat_id, now, now + OFFER_TTL),
            )
            view = _view(await _get(conn, int(cur.lastrowid)))
        return view

    async def set_message(self, offer_id: int, message_id: int) -> None:
        async with self.ctx.db.transaction() as conn:
            await conn.execute("UPDATE trade_offers SET message_id = ? WHERE id = ?", (message_id, offer_id))

    async def get(self, offer_id: int) -> OfferView:
        async with self.ctx.db.read() as conn:
            return _view(await _get(conn, offer_id))

    async def accept(self, offer_id: int, user_id: int) -> OfferOutcome:
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            row = await _get(conn, offer_id)
            if user_id != int(row["buyer_id"]):
                raise NotYourButton()
            if row["status"] != "pending":
                raise StaleAction()
            if int(row["expires_at"]) <= now:
                await _set_status(conn, offer_id, "expired", now)
                return OfferOutcome(_view(await _get(conn, offer_id)), "expired")
            seller, buyer = int(row["seller_id"]), int(row["buyer_id"])
            item_id, qty, price = row["item_id"], int(row["quantity"]), int(row["price"])
            buyer_ship = await repo.get_ship(conn, buyer)
            capacity = ship_capacity(buyer_ship["ship_class"], int(buyer_ship["cargo_level"]))
            used = repo.cargo_used(await repo.get_inventory(conn, buyer))
            need = qty * ITEMS[item_id].weight
            if used + need > capacity:
                raise GameError(f"📦 Не хватает места в трюме: нужно {need}, свободно {capacity - used}.")
            if await repo.get_balance(conn, buyer) < price:
                raise GameError(f"💸 Недостаточно кредитов: нужно {price}.")
            # 1) закрываем предложение (резерв снимается), 2) переводим товар и деньги.
            if not await _set_status(conn, offer_id, "accepted", now):
                raise StaleAction()
            seller_total = (await repo.get_inventory(conn, seller)).get(item_id, 0)
            if seller_total < qty:
                raise GameError("📦 У продавца больше нет этого товара.")
            await repo.remove_item(conn, seller, item_id, qty)
            await repo.add_item(conn, buyer, item_id, qty)
            if price > 0:
                await repo.change_balance(conn, buyer, -price, now)
                await progression.earn(conn, seller, price, now)
            await repo.add_ledger(conn, buyer, "p2p_buy", -price, now, item_id=item_id, quantity=qty,
                                  counterparty_id=seller, ref_type="offer", ref_id=offer_id)
            await repo.add_ledger(conn, seller, "p2p_sell", price, now, item_id=item_id, quantity=-qty,
                                  counterparty_id=buyer, ref_type="offer", ref_id=offer_id)
            sp, bp = Progress(), Progress()
            await progression.check_achievements(conn, seller, now, sp)
            await progression.check_achievements(conn, buyer, now, bp)
            view = _view(await _get(conn, offer_id))
        return OfferOutcome(view, "accepted", seller_progress=sp, buyer_progress=bp)

    async def decline(self, offer_id: int, user_id: int) -> OfferOutcome:
        return await self._close(offer_id, user_id, "declined")

    async def cancel(self, offer_id: int, user_id: int) -> OfferOutcome:
        return await self._close(offer_id, user_id, "cancelled")

    async def _close(self, offer_id: int, user_id: int, status: str) -> OfferOutcome:
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            row = await _get(conn, offer_id)
            allowed = int(row["buyer_id"]) if status == "declined" else int(row["seller_id"])
            if user_id != allowed:
                raise NotYourButton()
            if row["status"] != "pending":
                raise StaleAction()
            final = "expired" if int(row["expires_at"]) <= now else status
            if not await _set_status(conn, offer_id, final, now):
                raise StaleAction()
            view = _view(await _get(conn, offer_id))
        return OfferOutcome(view, final)

    async def list_for(self, user_id: int) -> tuple[list[OfferView], list[OfferView]]:
        """Активные входящие и исходящие предложения игрока."""
        async with self.ctx.db.read() as conn:
            now = self.ctx.clock.now()
            await repo.require_user(conn, user_id)
            cur = await conn.execute(
                f"{_SELECT} WHERE o.buyer_id = ? AND o.status = 'pending' AND o.expires_at > ? ORDER BY o.id DESC",
                (user_id, now))
            incoming = [_view(r) for r in await cur.fetchall()]
            cur = await conn.execute(
                f"{_SELECT} WHERE o.seller_id = ? AND o.status = 'pending' AND o.expires_at > ? ORDER BY o.id DESC",
                (user_id, now))
            outgoing = [_view(r) for r in await cur.fetchall()]
        return incoming, outgoing

    async def expire_due(self) -> list[ExpiredNotice]:
        notices: list[ExpiredNotice] = []
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            cur = await conn.execute(
                "SELECT id, chat_id, message_id FROM trade_offers WHERE status = 'pending' AND expires_at <= ?",
                (now,))
            for row in await cur.fetchall():
                if await _set_status(conn, int(row["id"]), "expired", now):
                    notices.append(ExpiredNotice("offer", int(row["id"]), row["chat_id"], row["message_id"],
                                                 f"⌛ Предложение #{row['id']} истекло, резерв товара снят."))
        return notices
