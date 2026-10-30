"""Inline-клавиатуры и формат callback_data (≤ 64 байт).

* TokenCB — мутирующие кнопки: одноразовый серверный токен + выбор.
* OfferCB / DuelCB — действия над P2P-предложением / вызовом; одноразовость
  обеспечивает статусная машина в БД, права — buyer/target/инициатор.
* NavCB — read-only навигация; owner=0 — кнопка общая.
"""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import ITEM_ORDER, ITEMS, MODULE_ORDER, MODULES, PLANETS, QUESTS, SHIP_CLASSES
from app.models import QuestView


class TokenCB(CallbackData, prefix="tk"):
    token: str
    choice: str


class OfferCB(CallbackData, prefix="of"):
    action: str        # a — принять, d — отклонить, c — отменить
    offer_id: int


class DuelCB(CallbackData, prefix="du"):
    action: str        # a — принять, d — отклонить, c — отменить
    challenge_id: int


class NavCB(CallbackData, prefix="nv"):
    view: str
    owner: int
    arg: str = ""


def token_button(text: str, token: str, choice: str) -> InlineKeyboardButton:
    data = TokenCB(token=token, choice=choice).pack()
    assert len(data.encode()) <= 64
    return InlineKeyboardButton(text=text, callback_data=data)


def nav_button(text: str, view: str, owner: int, arg: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=NavCB(view=view, owner=owner, arg=arg).pack())


def market_list_kb(owner: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for item_id in ITEM_ORDER:
        b.add(nav_button(ITEMS[item_id].title, "mi", owner, item_id))
    b.adjust(2)
    b.row(nav_button("🔄 Обновить", "mk", owner))
    return b.as_markup()


def market_item_kb(owner: int, token: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(*(token_button(f"🛒 Купить {q}", token, f"b{q}") for q in (1, 5, 10)))
    b.row(*(token_button(f"💵 Продать {q}", token, f"s{q}") for q in (1, 5, 10)))
    b.row(nav_button("⬅️ К рынку", "mk", owner))
    return b.as_markup()


def travel_kb(token: str, costs: dict[str, int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for dest, cost in costs.items():
        b.add(token_button(f"{PLANETS[dest].title} (🔋{cost})", token, dest))
    b.adjust(2)
    return b.as_markup()


def single_action_kb(text: str, token: str, choice: str = "go") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[token_button(text, token, choice)]])


def upgrade_kb(token: str, levels: dict[str, int], costs: dict[str, int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in MODULE_ORDER:
        if m in costs:
            b.add(token_button(f"{MODULES[m]} → {levels[m] + 1} ({costs[m]} кр.)", token, m))
    b.adjust(1)
    return b.as_markup()


def shipyard_kb(token: str, current: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for sc in SHIP_CLASSES.values():
        if sc.price is not None and sc.id != current:
            b.add(token_button(f"Купить «{sc.name}» за {sc.price}", token, sc.id))
    b.adjust(1)
    return b.as_markup()


def quests_kb(token: str, quests: list[QuestView]) -> InlineKeyboardMarkup | None:
    b = InlineKeyboardBuilder()
    for q in quests:
        if q.done and not q.claimed:
            b.add(token_button(f"🎁 {QUESTS[q.quest_id].reward_credits} кр. — {q.quest_id}", token, q.quest_id))
    b.adjust(1)
    markup = b.as_markup()
    return markup if markup.inline_keyboard else None


def offer_kb(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=OfferCB(action="a", offer_id=offer_id).pack()),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=OfferCB(action="d", offer_id=offer_id).pack())],
        [InlineKeyboardButton(text="🚫 Отменить (продавец)",
                              callback_data=OfferCB(action="c", offer_id=offer_id).pack())],
    ])


def duel_kb(challenge_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Принять", callback_data=DuelCB(action="a", challenge_id=challenge_id).pack()),
         InlineKeyboardButton(text="❌ Отклонить",
                              callback_data=DuelCB(action="d", challenge_id=challenge_id).pack())],
        [InlineKeyboardButton(text="🚫 Отменить (инициатор)",
                              callback_data=DuelCB(action="c", challenge_id=challenge_id).pack())],
    ])


def pager_kb(view: str, owner: int, page: int, pages: int) -> InlineKeyboardMarkup | None:
    if pages <= 1:
        return None
    row = []
    if page > 0:
        row.append(nav_button("⬅️", view, owner, str(page - 1)))
    row.append(nav_button(f"{page + 1}/{pages}", view, owner, str(page)))
    if page < pages - 1:
        row.append(nav_button("➡️", view, owner, str(page + 1)))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def top_kb(active: str) -> InlineKeyboardMarkup:
    labels = (("balance", "💰"), ("xp", "⭐"), ("pve", "☠️"), ("pvp", "⚔️"), ("clans", "🏰"))
    return InlineKeyboardMarkup(inline_keyboard=[[
        nav_button(("• " if key == active else "") + emoji, "tp", 0, key) for key, emoji in labels
    ]])


def disband_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        token_button("💥 Да, распустить", token, "yes"),
        token_button("Отмена", token, "no"),
    ]])
