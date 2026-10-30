"""Как игрок видит ошибки: ответом на команду и коротким алертом без HTML на кнопке."""

from __future__ import annotations

from aiogram.methods import SendMessage

from app.bot.middlewares import GameMiddleware
from app.bot.utils import ALERT_MAX_LEN, alert_text
from app.errors import GameError
from tests.test_callbacks import FakeCallback
from tests.test_handlers import Harness


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def test_alert_text_strips_html_and_fits_limit():
    assert alert_text("✍️ Формат: <code>/buy &lt;товар&gt;</code>") == "✍️ Формат: /buy <товар>"
    long = alert_text("🧪 " + "<b>Железо</b>: нужно 2000 " * 40)
    assert _utf16_len(long) <= ALERT_MAX_LEN
    assert long.endswith("…") and "<b>" not in long


async def test_callback_error_alert_is_short_plain_text(game):
    async def handler(event, _data):
        raise GameError("🧪 <b>Не хватает</b>: " + "💧 Вода: нужно 2000, доступно 0\n" * 20)

    cb = FakeCallback(1)
    await GameMiddleware()(handler, cb, {"game": game})
    text, alert = cb.answers[-1]
    assert alert is True
    assert _utf16_len(text) <= ALERT_MAX_LEN and "<b>" not in text


async def test_command_error_is_a_reply(game):
    h = Harness(game)
    await h.send(1, "/profile")  # не зарегистрирован
    sent = h.bot.calls[-1]
    assert isinstance(sent, SendMessage) and "/register" in sent.text
    assert sent.reply_parameters is not None and sent.reply_parameters.message_id == h.update_id + 10
