"""Токены inline-кнопок и обработчики с заглушками Telegram-объектов."""

from types import SimpleNamespace

import pytest

from app.bot.handlers import actions, trading
from app.bot.keyboards import DuelCB, NavCB, OfferCB, TokenCB
from app.bot.middlewares import GameMiddleware
from app.errors import InsufficientFunds, NotYourButton, StaleAction
from tests.conftest import give_items, make_user


class FakeMessage:
    def __init__(self, chat_id=-100):
        self.chat = SimpleNamespace(id=chat_id)
        self.edits: list[str] = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append(text)


class FakeCallback:
    def __init__(self, user_id, message=None):
        self.from_user = SimpleNamespace(id=user_id, is_bot=False, full_name=f"U{user_id}", username=None)
        self.message = message or FakeMessage()
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def test_callback_data_limits():
    for data in (
        TokenCB(token="f" * 12, choice="electronics").pack(),
        NavCB(view="mi", owner=10**13, arg="electronics").pack(),
        OfferCB(action="a", offer_id=10**12).pack(),
        DuelCB(action="c", challenge_id=10**12).pack(),
    ):
        assert len(data.encode()) <= 64


async def test_token_reuse_and_foreign_user(game):
    await make_user(game, 1)
    await make_user(game, 2)
    token = await game.tokens.issue(1, -100, "mine")
    with pytest.raises(NotYourButton):
        await game.tokens.peek(token, 2)
    with pytest.raises(NotYourButton):
        await game.mining.mine(2, token=token)
    await game.mining.mine(1, token=token)
    with pytest.raises(StaleAction):
        await game.mining.mine(1, token=token)


async def test_token_expiry_and_wrong_action(game, clock):
    await make_user(game, 1)
    token = await game.tokens.issue(1, None, "hunt", ttl=60)
    with pytest.raises(StaleAction):
        await game.mining.mine(1, token=token)  # токен другого действия
    clock.advance(61)
    with pytest.raises(StaleAction):
        await game.combat.hunt(1, token=token)


async def test_failed_action_keeps_token_usable(game):
    await make_user(game, 1, balance=0)
    token = await game.tokens.issue(1, None, "upgrade")
    with pytest.raises(InsufficientFunds):
        await game.ships.upgrade(1, "engine", token=token)
    async with game.db.transaction() as conn:
        await conn.execute("UPDATE users SET balance = 500 WHERE user_id = 1")
    r = await game.ships.upgrade(1, "engine", token=token)
    assert r.new_level == 1
    with pytest.raises(StaleAction):
        await game.ships.upgrade(1, "engine", token=token)


async def test_action_handler_double_click(game):
    await make_user(game, 1)
    token = await game.tokens.issue(1, -100, "market", {"planet": "earth", "item": "water"})
    data = TokenCB(token=token, choice="b5")
    cb = FakeCallback(1)
    await actions.cb_token(cb, data, game)
    assert (await game.accounts.profile(1)).inventory == {"water": 5}
    middleware = GameMiddleware()

    async def handler(event, _data):
        return await actions.cb_token(event, data, game)

    cb2 = FakeCallback(1)
    await middleware(handler, cb2, {"game": game})
    assert cb2.answers[-1] == ("⏳ Действие устарело, откройте меню снова", True)
    assert (await game.accounts.profile(1)).inventory == {"water": 5}


async def test_foreign_user_gets_alert(game):
    await make_user(game, 1)
    await make_user(game, 2)
    await give_items(game, 1, water=3)
    offer = await game.offers.create(1, 2, "water", 3, 30, -100)
    data = OfferCB(action="a", offer_id=offer.id)
    middleware = GameMiddleware()
    stranger = FakeCallback(3)

    async def handler(event, _data):
        return await trading.cb_offer(event, data, game)

    await middleware(handler, stranger, {"game": game})
    assert stranger.answers[-1] == ("⛔ Эта кнопка не для вас", True)
    buyer = FakeCallback(2)
    await middleware(handler, buyer, {"game": game})
    assert buyer.answers[-1][0] == "✅ Сделка совершена!"
    assert "сделка совершена" in buyer.message.edits[-1]
