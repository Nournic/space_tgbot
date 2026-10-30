"""Отмена и отклонение предложений и вызовов по ID, когда исходное сообщение потерялось."""

from __future__ import annotations

from aiogram.methods import EditMessageText

from tests.conftest import give_items, make_user
from tests.test_handlers import Harness


async def _two_players(game) -> Harness:
    await make_user(game, 1)
    await make_user(game, 2)
    return Harness(game)


async def test_seller_cancels_offer_and_original_is_updated(game):
    h = await _two_players(game)
    await give_items(game, 1, water=5)
    await h.send(1, "/offer water 5 100", reply_to=2)
    offer_msg_id = h.bot._next_id
    await h.send(1, "/offers cancel 1")
    assert "отменено продавцом" in h.bot.texts()[-1]
    edits = [c for c in h.bot.calls if isinstance(c, EditMessageText)]
    assert edits and edits[-1].message_id == offer_msg_id and edits[-1].reply_markup is None
    assert (await game.accounts.profile(1)).reserved == {}


async def test_buyer_declines_but_cannot_cancel(game):
    h = await _two_players(game)
    await give_items(game, 1, water=5)
    await game.offers.create(1, 2, "water", 2, 10, None)
    await h.send(2, "/offers cancel 1")
    assert "только продавец" in h.bot.texts()[-1]
    await h.send(2, "/offers decline 1")
    assert "отклонено покупателем" in h.bot.texts()[-1]
    await h.send(2, "/offers decline 1")
    assert "уже закрыто" in h.bot.texts()[-1]


async def test_challenger_cancels_duel_with_refund(game):
    h = await _two_players(game)
    await game.pvp.create(1, 2, 300, None)
    assert (await game.accounts.profile(1)).balance == 700
    await h.send(2, "/duels cancel 1")
    assert "только инициатор" in h.bot.texts()[-1]
    await h.send(1, "/duels cancel 1")
    assert "ставка возвращена" in h.bot.texts()[-1]
    assert (await game.accounts.profile(1)).balance == 1000


async def test_bad_arguments(game):
    h = await _two_players(game)
    for cmd in ("/offers drop 1", "/offers cancel x", "/duels cancel", "/duels cancel 99"):
        await h.send(1, cmd)
    texts = h.bot.texts()
    assert sum("Формат" in t for t in texts) == 2
    assert "целым числом" in texts[-3]
    assert "не найден" in texts[-1]
