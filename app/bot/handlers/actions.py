"""Единый обработчик мутирующих кнопок с одноразовыми токенами.

1. peek() — проверка владельца и свежести, определение типа действия.
2. Вызов сервиса с token: сервис погашает токен в той же транзакции, что и
   действие, поэтому повторное нажатие или старая клавиатура не сработают.
3. После commit — редактирование сообщения (ошибки Telegram не откатывают действие).
"""
from __future__ import annotations

import re

from aiogram import Router
from aiogram.types import CallbackQuery

from app.bot.formatting import esc
from app.bot.handlers.market import render_item_card, trade_text
from app.bot.handlers.progression import claim_text, render_quests
from app.bot.handlers.pve import hunt_again_kb, hunt_text
from app.bot.handlers.ship import (
    craft_text,
    mine_again_kb,
    mine_text,
    purchase_text,
    render_upgrades,
    repair_text,
    upgrade_text,
)
from app.bot.handlers.travel import render_travel, travel_result_text
from app.bot.keyboards import TokenCB
from app.bot.utils import cb_answer, safe_edit
from app.errors import StaleAction
from app.services import Game

router = Router(name="actions")

_MARKET_CHOICE = re.compile(r"^([bs])(1|5|10)$")


@router.callback_query(TokenCB.filter())
async def cb_token(callback: CallbackQuery, callback_data: TokenCB, game: Game) -> None:
    uid = callback.from_user.id
    token, choice = callback_data.token, callback_data.choice
    chat_id = callback.message.chat.id if callback.message else None
    action, payload = await game.tokens.peek(token, uid)

    if action == "market":
        m = _MARKET_CHOICE.match(choice)
        if not m:
            raise StaleAction()
        item_id, qty = str(payload.get("item")), int(m.group(2))
        if m.group(1) == "b":
            result = await game.economy.buy(uid, item_id, qty, token=token)
        else:
            result = await game.economy.sell(uid, item_id, qty, token=token)
        text, kb = await render_item_card(game, uid, chat_id, item_id, note=trade_text(result))
        await safe_edit(callback.message, text, kb)
        await cb_answer(callback, "✅ Готово")

    elif action == "travel":
        result = await game.travel.travel(uid, choice, token=token)
        text, kb = await render_travel(game, uid, chat_id, prefix=travel_result_text(result) + "\n\n")
        await safe_edit(callback.message, text, kb)
        await cb_answer(callback, "🚀 Прибыли!")

    elif action == "mine":
        result = await game.mining.mine(uid, token=token)
        await safe_edit(callback.message, mine_text(result), await mine_again_kb(game, uid, chat_id))
        await cb_answer(callback)

    elif action == "hunt":
        result = await game.combat.hunt(uid, token=token)
        kb = await hunt_again_kb(game, uid, chat_id) if result.hp_left > 0 else None
        await safe_edit(callback.message, hunt_text(result), kb)
        await cb_answer(callback, "🏆 Победа!" if result.won else "💥 Поражение")

    elif action == "upgrade":
        result = await game.ships.upgrade(uid, choice, token=token)
        text, kb = await render_upgrades(game, uid, chat_id, prefix=upgrade_text(result) + "\n\n")
        await safe_edit(callback.message, text, kb)
        await cb_answer(callback, "🔧 Улучшено")

    elif action == "shipyard":
        result = await game.ships.buy_ship(uid, choice, token=token)
        await safe_edit(callback.message, purchase_text(result))
        await cb_answer(callback, "🚀 Корабль куплен")

    elif action == "repair":
        result = await game.ships.repair(uid, None, token=token)
        await safe_edit(callback.message, repair_text(result))
        await cb_answer(callback, "🛠 Отремонтировано")

    elif action == "craft":
        result = await game.crafting.craft(uid, str(payload.get("item")), int(payload.get("qty", 0)), token=token)
        await safe_edit(callback.message, craft_text(result))
        await cb_answer(callback, "🛠 Готово")

    elif action == "quests":
        result = await game.quests.claim(uid, choice, token=token)
        text, kb = await render_quests(game, uid, chat_id, prefix=claim_text(result) + "\n\n")
        await safe_edit(callback.message, text, kb)
        await cb_answer(callback, "🎁 Награда получена")

    elif action == "clan_disband":
        if choice == "yes":
            view = await game.clans.disband(uid, token=token)
            await safe_edit(callback.message, f"💥 Клан «{esc(view.name)}» распущен. "
                                              f"Казна {view.treasury} кр. сгорела.")
            await cb_answer(callback, "Клан распущен")
        else:
            await game.tokens.discard(token, uid, "clan_disband")
            await safe_edit(callback.message, "↩️ Роспуск клана отменён.")
            await cb_answer(callback)
    else:
        raise StaleAction()
