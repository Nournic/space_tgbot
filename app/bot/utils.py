"""Вспомогательные функции Telegram-слоя: разбор аргументов и безопасные ответы."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from app.constants import ITEMS, PLANETS
from app.errors import ValidationError

log = logging.getLogger(__name__)

MAX_INT_ARG = 10_000_000

ITEM_ALIASES = {**{k: k for k in ITEMS}, **{v.name.casefold(): k for k, v in ITEMS.items()}}
PLANET_ALIASES = {**{k: k for k in PLANETS}, **{v.name.casefold(): k for k, v in PLANETS.items()}}


def display_name(user: User) -> str:
    return user.full_name or user.username or str(user.id)


def split_args(args: str | None) -> list[str]:
    return (args or "").split()


def parse_int(raw: str, what: str = "число", minimum: int = 1, maximum: int = MAX_INT_ARG) -> int:
    raw = raw.strip()
    if not raw or len(raw) > 12 or not raw.lstrip("-").isdigit() or raw.startswith("+"):
        raise ValidationError(f"🔢 {what.capitalize()} должно быть целым числом.")
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValidationError(f"🔢 {what.capitalize()} должно быть от {minimum} до {maximum}.")
    return value


def parse_item(raw: str) -> str:
    key = raw.strip().casefold()
    if key not in ITEM_ALIASES:
        raise ValidationError(f"❓ Неизвестный товар. Доступны: {', '.join(ITEMS)}.")
    return ITEM_ALIASES[key]


def parse_planet(raw: str) -> str:
    key = raw.strip().casefold()
    if key not in PLANET_ALIASES:
        raise ValidationError(f"❓ Неизвестная планета. Доступны: {', '.join(PLANETS)}.")
    return PLANET_ALIASES[key]


def reply_target(message: Message) -> User:
    """Пользователь, на сообщение которого ответили командой.

    В темах форума Telegram подставляет в reply_to_message служебное сообщение о
    создании темы, даже если игрок ни на что не отвечал. Такой «ответ» не считается.
    """
    reply = message.reply_to_message
    if reply is not None and (
        reply.forum_topic_created is not None
        or (message.is_topic_message and reply.message_id == message.message_thread_id)
    ):
        reply = None
    if reply is None or reply.from_user is None:
        raise ValidationError("↩️ Используйте команду ответом на сообщение другого игрока.")
    if reply.from_user.is_bot:
        raise ValidationError("🤖 С ботами играть нельзя — ответьте на сообщение игрока.")
    return reply.from_user


async def cb_answer(callback: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    try:
        await callback.answer(text, show_alert=alert)
    except TelegramAPIError as exc:
        log.debug("callback.answer failed: %s", exc)


async def safe_edit(message: Message | None, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Редактирует сообщение; ошибки Telegram не отменяют уже совершённое действие."""
    if message is None or not hasattr(message, "edit_text"):  # InaccessibleMessage — редактировать нельзя
        return
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            log.debug("edit_text failed: %s", exc)
    except TelegramAPIError as exc:
        log.debug("edit_text failed: %s", exc)
