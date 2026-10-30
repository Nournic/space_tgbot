"""Фоновая очистка: сообщения истёкших предложений и вызовов сохраняют содержимое."""

from __future__ import annotations

from aiogram.methods import EditMessageText

from app.models import ExpiredNotice
from app.tasks import notice_text, notify_expired
from tests.conftest import give_items, make_user
from tests.test_handlers import RecordingBot


async def test_expired_messages_keep_details(game, clock):
    await make_user(game, 1, name="Алиса")
    await make_user(game, 2, name="Боб")
    await give_items(game, 1, water=5)
    offer = await game.offers.create(1, 2, "water", 3, 40, -100)
    await game.offers.set_message(offer.id, 501)
    duel = await game.pvp.create(1, 2, 150, -100)
    await game.pvp.set_message(duel.id, 502)
    clock.advance(301)
    notices = await game.cleanup()
    bot = RecordingBot()
    await notify_expired(bot, notices, clock.now())
    edits = {c.message_id: c for c in bot.calls if isinstance(c, EditMessageText)}
    assert set(edits) == {501, 502}
    assert all(c.reply_markup is None for c in edits.values())
    offer_msg, duel_msg = edits[501].text, edits[502].text
    assert "P2P-предложение" in offer_msg and "3 ×" in offer_msg and "40" in offer_msg and "истекло" in offer_msg
    assert "Вызов на дуэль" in duel_msg and "150" in duel_msg and "ставка возвращена" in duel_msg


async def test_notice_without_message_is_skipped(game):
    bot = RecordingBot()
    await notify_expired(bot, [ExpiredNotice("offer", 1, None, None, "x")], 0)
    assert bot.calls == []


def test_notice_text_falls_back_to_short_text():
    assert notice_text(ExpiredNotice("offer", 7, 1, 2, "⌛ истекло"), 0) == "⌛ истекло"
