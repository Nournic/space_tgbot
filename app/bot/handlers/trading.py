"""P2P-сделки: /offer (ответом на сообщение покупателя), /offers и кнопки предложения."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import item_title, mention, offer_text
from app.bot.keyboards import OfferCB, offer_kb
from app.bot.utils import (
    cb_answer,
    close_by_id,
    display_name,
    edit_original,
    parse_close_args,
    parse_int,
    parse_item,
    reply_target,
    safe_edit,
    split_args,
)
from app.constants import MAX_PRICE, MAX_QTY
from app.errors import StaleAction, ValidationError
from app.services import Game
from app.services.base import format_duration

router = Router(name="trading")


@router.message(Command("offer"))
async def cmd_offer(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if len(args) != 3:
        raise ValidationError(
            "✍️ Формат: ответом на сообщение покупателя "
            "<code>/offer &lt;товар&gt; &lt;кол-во&gt; &lt;цена за всё&gt;</code>, "
            "например <code>/offer water 5 200</code>"
        )
    item_id = parse_item(args[0])
    qty = parse_int(args[1], "количество", 1, MAX_QTY)
    price = parse_int(args[2], "цена", 0, MAX_PRICE)
    buyer = reply_target(message)
    await game.accounts.touch_name(buyer.id, display_name(buyer))
    view = await game.offers.create(message.from_user.id, buyer.id, item_id, qty, price, message.chat.id)
    sent = await message.answer(
        offer_text(view, game.ctx.clock.now()) + "\n\nПринять или отклонить может только покупатель.",
        reply_markup=offer_kb(view.id),
    )
    await game.offers.set_message(view.id, sent.message_id)


@router.message(Command("offers"))
async def cmd_offers(message: Message, command: CommandObject, game: Game) -> None:
    uid = message.from_user.id
    close = parse_close_args(split_args(command.args), "offers")
    now = game.ctx.clock.now()
    if close is not None:
        action, offer_id = close
        service = game.offers.cancel if action == "cancel" else game.offers.decline
        outcome = await close_by_id(
            service,
            offer_id,
            uid,
            "⛔ Отменить может только продавец, отклонить — только покупатель.",
            f"⌛ Предложение #{offer_id} уже закрыто или не найдено.",
        )
        text = offer_text(outcome.offer, now)
        await edit_original(message.bot, outcome.offer.chat_id, outcome.offer.message_id, text)
        await message.reply(text)
        return
    incoming, outgoing = await game.offers.list_for(uid)
    lines = ["🤝 <b>Активные P2P-предложения</b>", "", "📥 Входящие:"]
    lines += [
        f"#{o.id} от {mention(o.seller_id, o.seller_name)}: {o.quantity} × {item_title(o.item_id)} "
        f"за {o.price} кр. (ещё {format_duration(o.expires_at - now)})"
        for o in incoming
    ] or ["—"]
    lines += ["", "📤 Исходящие:"]
    lines += [
        f"#{o.id} для {mention(o.buyer_id, o.buyer_name)}: {o.quantity} × {item_title(o.item_id)} "
        f"за {o.price} кр. (ещё {format_duration(o.expires_at - now)})"
        for o in outgoing
    ] or ["—"]
    if incoming or outgoing:
        lines += ["", "Отменить своё: <code>/offers cancel ID</code>, отклонить: <code>/offers decline ID</code>"]
    await message.answer("\n".join(lines))


@router.callback_query(OfferCB.filter())
async def cb_offer(callback: CallbackQuery, callback_data: OfferCB, game: Game) -> None:
    uid, oid = callback.from_user.id, callback_data.offer_id
    if callback_data.action == "a":
        outcome = await game.offers.accept(oid, uid)
    elif callback_data.action == "d":
        outcome = await game.offers.decline(oid, uid)
    elif callback_data.action == "c":
        outcome = await game.offers.cancel(oid, uid)
    else:
        raise StaleAction()
    # Уведомление — после commit; сбой Telegram не отменяет сделку.
    await safe_edit(callback.message, offer_text(outcome.offer, game.ctx.clock.now()))
    if outcome.status == "expired":
        raise StaleAction()
    answers = {
        "accepted": "✅ Сделка совершена!",
        "declined": "Предложение отклонено",
        "cancelled": "Предложение отменено",
    }
    await cb_answer(callback, answers[outcome.status])
