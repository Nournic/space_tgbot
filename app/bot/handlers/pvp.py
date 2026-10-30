"""PvP-дуэли: /challenge (ответом на сообщение), /duels и кнопки вызова."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import challenge_text, duel_text, mention
from app.bot.keyboards import DuelCB, duel_kb
from app.bot.utils import cb_answer, display_name, parse_int, reply_target, safe_edit, split_args
from app.constants import MAX_STAKE
from app.errors import StaleAction, ValidationError
from app.services import Game

router = Router(name="pvp")

STATUS_RU = {
    "pending": "⏳ ждёт",
    "resolved": "⚔️ состоялся",
    "declined": "❌ отклонён",
    "cancelled": "🚫 отменён",
    "expired": "⌛ истёк",
}


@router.message(Command("challenge"))
async def cmd_challenge(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if len(args) > 1:
        raise ValidationError("✍️ Формат: ответом на сообщение игрока <code>/challenge [ставка]</code>")
    stake = parse_int(args[0], "ставка", 0, MAX_STAKE) if args else 0
    target = reply_target(message)
    await game.accounts.touch_name(target.id, display_name(target))
    view = await game.pvp.create(message.from_user.id, target.id, stake, message.chat.id)
    sent = await message.answer(
        challenge_text(view, game.ctx.clock.now()) + "\n\nПринять может только вызванный игрок.",
        reply_markup=duel_kb(view.id),
    )
    await game.pvp.set_message(view.id, sent.message_id)


@router.message(Command("duels"))
async def cmd_duels(message: Message, game: Game) -> None:
    uid = message.from_user.id
    items = await game.pvp.list_for(uid)
    if not items:
        await message.answer("⚔️ У вас пока нет вызовов. Ответьте на сообщение игрока: <code>/challenge 50</code>")
        return
    lines = ["⚔️ <b>Ваши дуэли</b>"]
    for c in items:
        role = "→" if c.challenger_id == uid else "←"
        other = (c.target_id, c.target_name) if c.challenger_id == uid else (c.challenger_id, c.challenger_name)
        result = ""
        if c.status == "resolved":
            result = (
                " · 🤝 ничья" if c.winner_id is None else (" · 🏆 победа" if c.winner_id == uid else " · 🩸 поражение")
            )
        lines.append(f"#{c.id} {role} {mention(*other)} · ставка {c.stake} · {STATUS_RU[c.status]}{result}")
    await message.answer("\n".join(lines))


@router.callback_query(DuelCB.filter())
async def cb_duel(callback: CallbackQuery, callback_data: DuelCB, game: Game) -> None:
    uid, cid = callback.from_user.id, callback_data.challenge_id
    now = game.ctx.clock.now()
    if callback_data.action == "a":
        result = await game.pvp.accept(cid, uid)
        if result.status == "expired":
            await safe_edit(callback.message, challenge_text(result.challenge, now))
            raise StaleAction()
        await safe_edit(callback.message, duel_text(result))
        await cb_answer(callback, "⚔️ Дуэль состоялась!")
    elif callback_data.action == "d":
        view = await game.pvp.decline(cid, uid)
        await safe_edit(callback.message, challenge_text(view, now))
        await cb_answer(callback, "Вызов отклонён")
    elif callback_data.action == "c":
        view = await game.pvp.cancel(cid, uid)
        await safe_edit(callback.message, challenge_text(view, now))
        await cb_answer(callback, "Вызов отменён")
    else:
        raise StaleAction()
