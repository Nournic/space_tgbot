"""Сборка роутеров, middleware и списка команд."""

from __future__ import annotations

from functools import lru_cache

from aiogram import Dispatcher, F, Router
from aiogram.types import BotCommand

from app.bot.handlers import actions, admin, clans, common, market, progression, pve, pvp, ship, trading, travel
from app.bot.middlewares import GameMiddleware
from app.bot.throttle import Throttle, ThrottleMiddleware
from app.services import Game

COMMANDS = [
    ("start", "Начало игры"),
    ("help", "Список команд"),
    ("register", "Регистрация"),
    ("profile", "Профиль"),
    ("stats", "Статистика"),
    ("inventory", "Трюм"),
    ("history", "История операций"),
    ("map", "Карта"),
    ("travel", "Перелёт"),
    ("market", "Рынок планеты"),
    ("prices", "Цены всех планет"),
    ("buy", "Купить: /buy water 5"),
    ("sell", "Продать: /sell iron 2"),
    ("ship", "Корабль"),
    ("shipyard", "Верфь"),
    ("upgrade", "Улучшения модулей"),
    ("repair", "Ремонт"),
    ("mine", "Добыча ресурсов"),
    ("recipes", "Рецепты"),
    ("craft", "Производство"),
    ("hunt", "Охота на пиратов"),
    ("challenge", "Дуэль (ответом на сообщение)"),
    ("duels", "Мои дуэли"),
    ("offer", "P2P-предложение (ответом)"),
    ("offers", "Мои предложения"),
    ("quests", "Ежедневные задания"),
    ("claim", "Получить награду задания"),
    ("achievements", "Достижения"),
    ("top", "Рейтинги"),
    ("clan", "Кланы"),
    ("events", "Событие дня"),
]


def bot_commands() -> list[BotCommand]:
    return [BotCommand(command=c, description=d) for c, d in COMMANDS]


@lru_cache(maxsize=1)
def build_dispatcher() -> Dispatcher:
    """Роутеры модулей — синглтоны aiogram, поэтому диспетчер собирается один раз на процесс.

    Экземпляр Game передаётся через workflow data: ``dp["game"] = game`` или
    ``dp.feed_update(bot, update, game=game)``. Антифлуд включается так же: ``dp["throttle"]``.
    """
    root = Router(name="root")
    # Игнорируем апдейты без отправителя-человека (каналы, анонимные админы, боты).
    root.message.filter(F.from_user.is_bot.is_(False))
    root.callback_query.filter(F.from_user.is_bot.is_(False))
    for module in (common, market, travel, ship, pve, pvp, trading, progression, clans, admin, actions):
        root.include_router(module.router)
    dp = Dispatcher()
    throttle = ThrottleMiddleware()  # раньше GameMiddleware: лишние апдейты не трогают БД
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)
    middleware = GameMiddleware()
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    dp.include_router(root)
    return dp


def setup_dispatcher(game: Game, admin_ids: frozenset[int] = frozenset()) -> Dispatcher:
    dp = build_dispatcher()
    dp["admin_ids"] = admin_ids
    dp["game"] = game
    dp["throttle"] = Throttle()
    return dp
