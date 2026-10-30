"""Вспомогательные функции Telegram-слоя: разбор аргументов и безопасные ответы."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from app.constants import ITEMS, PLANETS
from app.errors import NotYourButton, StaleAction, ValidationError

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
    """Пользователь, на сообщение которого ответили командой."""
    reply = message.reply_to_message
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


CLOSE_ACTIONS = ("cancel", "decline")


def parse_close_args(args: list[str], command: str) -> tuple[str, int] | None:
    """``/offers cancel 12`` → ("cancel", 12); без аргументов — None (показать список)."""
    if not args:
        return None
    if len(args) != 2 or args[0].lower() not in CLOSE_ACTIONS:
        raise ValidationError(
            f"✍️ Формат: <code>/{command} cancel ID</code> — отменить своё, "
            f"<code>/{command} decline ID</code> — отклонить входящее."
        )
    return args[0].lower(), parse_int(args[1], "ID", 1, 10**12)


async def close_by_id(close, object_id: int, user_id: int, not_yours: str, closed: str):
    """Закрывает предложение или вызов командой; ошибки кнопок переводятся в текст для команды."""
    try:
        return await close(object_id, user_id)
    except NotYourButton:
        raise ValidationError(not_yours) from None
    except StaleAction:
        raise ValidationError(closed) from None


async def edit_original(bot: Bot, chat_id: int | None, message_id: int | None, text: str) -> None:
    """Обновляет исходное сообщение предложения/вызова и убирает кнопки (после commit)."""
    if chat_id is None or message_id is None:
        return
    try:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=None)
    except TelegramAPIError as exc:
        log.debug("edit original %s/%s failed: %s", chat_id, message_id, exc)
