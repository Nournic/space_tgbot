"""Общие команды: /start, /help, /register, /profile, /stats, /inventory, /history, /events."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import esc, history_text, inventory_text, profile_text, stats_text
from app.bot.keyboards import NavCB, pager_kb
from app.bot.utils import cb_answer, display_name, safe_edit
from app.constants import HUNT_ENERGY, MINE_ENERGY, PLANETS, PRICE_MAX_PCT, PRICE_MIN_PCT, START_BALANCE
from app.errors import NotYourButton
from app.services import Game

router = Router(name="common")

HELP_TEXT = f"""🚀 <b>Космический Трейдер</b> — команды

<b>Аккаунт</b>
/register — регистрация (повтор безопасен)
/profile, /stats — профиль и статистика
/inventory — трюм
/history — последние операции

<b>Торговля и карта</b>
/map, /travel — карта и перелёты (<code>/travel mars</code>)
/market — рынок текущей планеты
/prices — цены всех планет
<code>/buy water 5</code>, <code>/sell iron 2</code>

<b>Корабль</b>
/ship — корабль, /shipyard — верфь (<code>/shipyard scout</code>)
/upgrade — модули (<code>/upgrade engine</code>)
/repair — ремонт (<code>/repair</code> или <code>/repair 20</code>)

<b>Ресурсы</b>
/mine — добыча ({MINE_ENERGY} 🔋), /recipes — рецепты
<code>/craft electronics 2</code>

<b>Бои</b>
/hunt — охота на пиратов ({HUNT_ENERGY} 🔋)
<code>/challenge 100</code> — ответом на сообщение игрока: дуэль со ставкой
/duels — ваши вызовы (<code>/duels cancel ID</code> — отменить)

<b>Сделки</b>
<code>/offer water 5 200</code> — ответом на сообщение покупателя: продать 5 воды за 200 кр.
/offers — активные предложения (<code>/offers cancel ID</code> — отменить)

<b>Прогресс</b>
/quests, <code>/claim daily_sell</code> — ежедневные задания
/achievements — достижения, /top — рейтинги, /events — событие дня

<b>Кланы</b>
/clan — справка: create, list, join, leave, info, donate, transfer, disband

💡 Кредиты — вымышленная игровая валюта, не обмениваются на деньги."""


@router.message(CommandStart())
async def cmd_start(message: Message, game: Game) -> None:
    registered = await game.accounts.is_registered(message.from_user.id)
    lead = (
        "С возвращением, пилот! Откройте /profile или /market."
        if registered
        else f"Нажмите /register — вы получите шаттл, {START_BALANCE} кредитов и старт на Земле."
    )
    await message.answer(
        "🌌 <b>Добро пожаловать в «Космический Трейдер»!</b>\n\n"
        f"Покупайте дешевле, летайте между {len(PLANETS)} планетами и продавайте дороже. Добывайте ресурсы, "
        "производите товары, улучшайте корабль, охотьтесь на пиратов, вызывайте друзей на дуэли "
        "и создавайте кланы.\n\n"
        f"{lead}\n\n"
        "⚡ Быстрый старт: /register → /market → купите воду на Земле → /travel → продайте дороже.\n"
        "Все команды: /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("register"))
async def cmd_register(message: Message, game: Game) -> None:
    result = await game.accounts.register(message.from_user.id, display_name(message.from_user))
    p = result.profile
    if result.created:
        text = (
            f"✅ Пилот <b>{esc(p.display_name)}</b> зарегистрирован!\n"
            f"🚀 Корабль: {esc(p.ship.class_name)}, 💰 {p.balance} кр., 📍 Земля.\n"
            "Дальше: /market, /map, /help"
        )
    else:
        text = f"👋 {esc(p.display_name)}, вы уже зарегистрированы — прогресс сохранён. /profile"
    await message.answer(text)


@router.message(Command("profile"))
async def cmd_profile(message: Message, game: Game) -> None:
    p = await game.accounts.profile(message.from_user.id)
    await message.answer(profile_text(p, game.ctx.clock.now()))


@router.message(Command("stats"))
async def cmd_stats(message: Message, game: Game) -> None:
    p = await game.accounts.profile(message.from_user.id)
    await message.answer(
        f"👤 <b>{esc(p.display_name)}</b> · ⭐ ур. {p.level} · 💰 {p.balance} кр.\n\n" f"{stats_text(p.stats)}"
    )


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, game: Game) -> None:
    p = await game.accounts.profile(message.from_user.id)
    await message.answer(inventory_text(p))


@router.message(Command("history"))
async def cmd_history(message: Message, game: Game) -> None:
    uid = message.from_user.id
    page = await game.accounts.history(uid, 0)
    await message.answer(history_text(page), reply_markup=pager_kb("hi", uid, page.page, page.pages))


@router.callback_query(NavCB.filter(F.view == "hi"))
async def cb_history(callback: CallbackQuery, callback_data: NavCB, game: Game) -> None:
    if callback.from_user.id != callback_data.owner:
        raise NotYourButton()
    page_no = int(callback_data.arg) if callback_data.arg.isdigit() else 0
    page = await game.accounts.history(callback.from_user.id, page_no)
    await safe_edit(callback.message, history_text(page), pager_kb("hi", callback.from_user.id, page.page, page.pages))
    await cb_answer(callback)


@router.message(Command("events"))
async def cmd_events(message: Message, game: Game) -> None:
    day, event = game.events.current()
    await message.answer(
        f"🌐 <b>Событие дня</b> ({day} UTC)\n\n"
        f"<b>{esc(event.title)}</b>\n{esc(event.description)}\n\n"
        "Событие меняется в 00:00 UTC и одинаково для всех. "
        f"Итоговая цена ограничена {PRICE_MIN_PCT}–{PRICE_MAX_PCT}% базовой."
    )
