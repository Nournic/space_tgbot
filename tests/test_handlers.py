"""Сквозные тесты: апдейты проходят через настоящий Dispatcher/роутеры, Bot подменён записью запросов."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, ForumTopicCreated, Message, Update, User

from app.bot.middlewares import INTERNAL_ERROR
from app.bot.routers import build_dispatcher
from tests.conftest import give_items, make_user, snapshot

CHAT = Chat(id=-1001, type="supergroup", title="Test")


class RecordingBot(Bot):
    def __init__(self) -> None:
        super().__init__("123456:TEST-TOKEN")
        self.calls: list[TelegramMethod] = []
        self._next_id = 1000

    async def __call__(self, method, request_timeout=None):  # type: ignore[override]
        self.calls.append(method)
        if isinstance(method, SendMessage):
            self._next_id += 1
            return Message(
                message_id=self._next_id,
                date=datetime.now(UTC),
                chat=CHAT,
                text=method.text,
                reply_markup=method.reply_markup,
            )
        return True

    def texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, (SendMessage, EditMessageText))]

    def last_markup(self):
        for c in reversed(self.calls):
            if isinstance(c, (SendMessage, EditMessageText)) and c.reply_markup is not None:
                return c.reply_markup
        return None

    def answers(self) -> list[tuple[str | None, bool | None]]:
        return [(c.text, c.show_alert) for c in self.calls if isinstance(c, AnswerCallbackQuery)]


def user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"Pilot{uid}")


class Harness:
    def __init__(self, game) -> None:
        self.game = game
        self.bot = RecordingBot()
        self.dp = build_dispatcher()
        self.update_id = 0

    async def feed(self, update: Update) -> None:
        await self.dp.feed_update(self.bot, update, game=self.game)

    async def send(
        self, uid: int, text: str, reply_to: int | None = None, topic_by: int | None = None, thread_id: int = 77
    ) -> None:
        """topic_by — сообщение в теме форума, созданной этим игроком (без явного ответа)."""
        self.update_id += 1
        reply = None
        if reply_to is not None:
            reply = Message(message_id=1, date=datetime.now(UTC), chat=CHAT, from_user=user(reply_to), text="привет")
        elif topic_by is not None:
            reply = Message(
                message_id=thread_id,
                date=datetime.now(UTC),
                chat=CHAT,
                from_user=user(topic_by),
                forum_topic_created=ForumTopicCreated(name="Тема", icon_color=0x6FB9F0),
            )
        msg = Message(
            message_id=self.update_id + 10,
            date=datetime.now(UTC),
            chat=CHAT,
            from_user=user(uid),
            text=text,
            reply_to_message=reply,
            message_thread_id=thread_id if topic_by is not None else None,
            is_topic_message=True if topic_by is not None else None,
        )
        await self.feed(Update(update_id=self.update_id, message=msg))

    async def press(self, uid: int, data: str) -> None:
        self.update_id += 1
        msg = Message(message_id=5, date=datetime.now(UTC), chat=CHAT, text="menu")
        cb = CallbackQuery(id=str(self.update_id), from_user=user(uid), chat_instance="ci", data=data, message=msg)
        await self.feed(Update(update_id=self.update_id, callback_query=cb))

    def button(self, text_part: str) -> str:
        markup = self.bot.last_markup()
        for row in markup.inline_keyboard:
            for b in row:
                if text_part in b.text:
                    return b.callback_data
        raise AssertionError(f"кнопка «{text_part}» не найдена")


@pytest.fixture
def h(game) -> Harness:
    return Harness(game)


async def test_all_commands_respond_without_internal_errors(h, game):
    await h.send(1, "/start")
    await h.send(1, "/register")
    await h.send(1, "/register")
    await give_items(game, 1, water=4, silicon=2)
    for cmd in (
        "/help",
        "/profile",
        "/stats",
        "/inventory",
        "/history",
        "/map",
        "/market",
        "/prices",
        "/buy water 2",
        "/sell water 1",
        "/ship",
        "/shipyard",
        "/upgrade",
        "/repair",
        "/mine",
        "/recipes",
        "/craft fuel_cell 1",
        "/hunt",
        "/duels",
        "/offers",
        "/quests",
        "/claim daily_sell",
        "/achievements",
        "/top",
        "/top xp",
        "/clan",
        "/clan list",
        "/events",
        "/travel venus",
    ):
        await h.send(1, cmd)
    texts = h.bot.texts()
    assert INTERNAL_ERROR not in texts
    assert any("зарегистрирован!" in t for t in texts)
    assert any("уже зарегистрированы" in t for t in texts)
    assert any("Перелёт" in t and "Венера" in t for t in texts)


async def test_validation_messages(h):
    await h.send(1, "/register")
    for cmd in (
        "/buy",
        "/buy water",
        "/buy gold 1",
        "/buy water -1",
        "/buy water 0",
        "/buy water 99999999999",
        "/sell water abc",
        "/travel pluto",
        "/craft",
        "/craft water 1",
        "/claim",
        "/clan join x",
        "/clan create ab",
        "/offer water 1 1",
        "/challenge 10",
    ):
        await h.send(1, cmd)
    texts = h.bot.texts()
    assert INTERNAL_ERROR not in texts
    assert len(texts) == 16
    await h.send(2, "/profile")
    assert "/register" in h.bot.texts()[-1]


async def test_market_buttons_flow(h, game):
    await h.send(1, "/register")
    await h.send(1, "/market")
    await h.press(1, h.button("Вода"))
    buy5 = h.button("Купить 5")
    await h.press(2, buy5)  # чужой игрок
    assert h.bot.answers()[-1] == ("⛔ Эта кнопка не для вас", True)
    await h.press(1, buy5)
    assert (await game.accounts.profile(1)).inventory == {"water": 5}
    await h.press(1, buy5)  # повтор старой кнопки
    assert h.bot.answers()[-1] == ("⏳ Действие устарело, откройте меню снова", True)
    assert (await game.accounts.profile(1)).inventory == {"water": 5}
    await h.press(1, h.button("Продать 1"))  # новая клавиатура после успеха
    assert (await game.accounts.profile(1)).inventory == {"water": 4}


async def test_travel_buttons_flow(h, game):
    await h.send(1, "/register")
    await h.send(1, "/map")
    await h.press(1, h.button("Марс"))
    assert (await game.accounts.profile(1)).planet_id == "mars"


async def test_offer_and_duel_via_replies(h, game):
    await h.send(1, "/register")
    await h.send(2, "/register")
    await give_items(game, 1, water=5)
    await h.send(1, "/offer water 5 100", reply_to=2)
    accept = h.button("Принять")
    await h.press(1, accept)  # продавец не может принять
    assert h.bot.answers()[-1][1] is True
    await h.press(2, accept)
    assert (await game.accounts.profile(2)).inventory == {"water": 5}
    await h.send(1, "/challenge 50", reply_to=2)
    await h.press(2, h.button("Принять"))
    p1, p2 = await game.accounts.profile(1), await game.accounts.profile(2)
    assert p1.stats["pvp_wins"] + p2.stats["pvp_wins"] + p1.stats["pvp_draws"] >= 1
    assert INTERNAL_ERROR not in h.bot.texts()


async def test_clan_disband_flow(h, game):
    await h.send(1, "/register")
    await h.send(1, "/clan create Орион")
    await h.send(1, "/clan disband")
    await h.press(1, h.button("Да, распустить"))
    assert await game.clans.my_clan_id(1) is None
    assert any("распущен" in t for t in h.bot.texts())


async def test_topic_root_is_not_a_reply(h, game):
    # В теме форума reply_to_message указывает на создание темы — это не ответ игроку 2.
    await h.send(1, "/register")
    await make_user(game, 2)
    await h.send(1, "/clan create Орион")
    await h.send(2, "/clan join 1")
    await give_items(game, 1, water=5)
    before = await snapshot(game, 1)
    for cmd in ("/clan transfer", "/challenge 100", "/offer water 5 0"):
        await h.send(1, cmd, topic_by=2)
        assert "ответом на сообщение" in h.bot.texts()[-1]
    assert (await game.clans.info(1)).leader_id == 1
    assert await snapshot(game, 1) == before
