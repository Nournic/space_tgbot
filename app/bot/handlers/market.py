"""Рынок: /market, /prices, /buy, /sell и навигация по товарам."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import item_title, market_text, planet_title, prices_text, progress_lines
from app.bot.keyboards import NavCB, market_item_kb, market_list_kb, pager_kb
from app.bot.utils import cb_answer, parse_int, parse_item, safe_edit, split_args
from app.clock import utc_date
from app.constants import ITEM_ORDER, ITEMS, MAX_QTY, PRICES_PAGE_SIZE
from app.errors import NotYourButton, ValidationError
from app.models import TradeResult
from app.services import Game

router = Router(name="market")


async def render_market(game: Game, user_id: int) -> str:
    p = await game.accounts.profile(user_id)
    _, event = game.events.current()
    return market_text(p.planet_id, game.economy.prices_on(p.planet_id), p, game.ctx.clock.now(), event.title)


async def render_item_card(game: Game, user_id: int, chat_id: int | None, item_id: str, note: str = ""):
    p = await game.accounts.profile(user_id)
    buy, sell = game.economy.prices_on(p.planet_id)[item_id]
    available = p.inventory.get(item_id, 0) - p.reserved.get(item_id, 0)
    token = await game.tokens.issue(user_id, chat_id, "market", {"planet": p.planet_id, "item": item_id})
    header = note + "\n\n" if note else ""
    text = (
        f"{header}"
        f"🏪 {planet_title(p.planet_id)} — <b>{item_title(item_id)}</b>\n"
        f"Покупка: <b>{buy}</b> кр. | Продажа: <b>{sell}</b> кр. | Вес: {ITEMS[item_id].weight}\n"
        f"У вас: {p.inventory.get(item_id, 0)} (доступно {max(0, available)})\n"
        f"💰 {p.balance} кр. | 📦 {p.cargo_used}/{p.ship.capacity}"
    )
    return text, market_item_kb(user_id, token)


def trade_text(r: TradeResult) -> str:
    verb = "🛒 Куплено" if r.op == "buy" else "💵 Продано"
    return (
        f"{verb}: <b>{r.quantity} × {item_title(r.item_id)}</b> по {r.unit_price} = <b>{r.total}</b> кр.\n"
        f"💰 Баланс: {r.balance} | 📦 Трюм: {r.cargo_used}/{r.capacity} | на борту: {r.owned}"
        f"{progress_lines(r.progress)}"
    )


@router.message(Command("market"))
async def cmd_market(message: Message, game: Game) -> None:
    uid = message.from_user.id
    await message.answer(await render_market(game, uid), reply_markup=market_list_kb(uid))


@router.callback_query(NavCB.filter(F.view == "mk"))
async def cb_market(callback: CallbackQuery, callback_data: NavCB, game: Game) -> None:
    if callback.from_user.id != callback_data.owner:
        raise NotYourButton()
    uid = callback.from_user.id
    await safe_edit(callback.message, await render_market(game, uid), market_list_kb(uid))
    await cb_answer(callback)


@router.callback_query(NavCB.filter(F.view == "mi"))
async def cb_market_item(callback: CallbackQuery, callback_data: NavCB, game: Game) -> None:
    if callback.from_user.id != callback_data.owner:
        raise NotYourButton()
    if callback_data.arg not in ITEMS:
        raise ValidationError("❓ Неизвестный товар.")
    chat_id = callback.message.chat.id if callback.message else None
    text, kb = await render_item_card(game, callback.from_user.id, chat_id, callback_data.arg)
    await safe_edit(callback.message, text, kb)
    await cb_answer(callback)


def _parse_trade_args(command: CommandObject, verb: str) -> tuple[str, int]:
    args = split_args(command.args)
    if len(args) != 2:
        raise ValidationError(
            f"✍️ Формат: <code>/{verb} &lt;товар&gt; &lt;количество&gt;</code>, "
            f"например <code>/{verb} water 5</code>"
        )
    return parse_item(args[0]), parse_int(args[1], "количество", 1, MAX_QTY)


@router.message(Command("buy"))
async def cmd_buy(message: Message, command: CommandObject, game: Game) -> None:
    item_id, qty = _parse_trade_args(command, "buy")
    result = await game.economy.buy(message.from_user.id, item_id, qty)
    await message.answer(trade_text(result))


@router.message(Command("sell"))
async def cmd_sell(message: Message, command: CommandObject, game: Game) -> None:
    item_id, qty = _parse_trade_args(command, "sell")
    result = await game.economy.sell(message.from_user.id, item_id, qty)
    await message.answer(trade_text(result))


def _prices_page(game: Game, page: int) -> tuple[str, int, int]:
    pages = -(-len(ITEM_ORDER) // PRICES_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    items = list(ITEM_ORDER[page * PRICES_PAGE_SIZE : (page + 1) * PRICES_PAGE_SIZE])
    text = prices_text(game.economy.price_table(), items, page, pages, utc_date(game.ctx.clock.now()))
    return text, page, pages


@router.message(Command("prices"))
async def cmd_prices(message: Message, game: Game) -> None:
    text, page, pages = _prices_page(game, 0)
    await message.answer(text, reply_markup=pager_kb("pr", 0, page, pages))


@router.callback_query(NavCB.filter(F.view == "pr"))
async def cb_prices(callback: CallbackQuery, callback_data: NavCB, game: Game) -> None:
    text, page, pages = _prices_page(game, int(callback_data.arg) if callback_data.arg.isdigit() else 0)
    await safe_edit(callback.message, text, pager_kb("pr", 0, page, pages))
    await cb_answer(callback)
