"""Антифлуд: лишние команды и нажатия одного игрока отбрасываются до обращения к игре."""

from __future__ import annotations

from aiogram.methods import SendMessage
from aiogram.types import Update

from app.bot.throttle import TOO_FAST, Throttle
from tests.test_handlers import Harness


class FakeMonotonic:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class ThrottledHarness(Harness):
    def __init__(self, game, throttle: Throttle) -> None:
        super().__init__(game)
        self.throttle = throttle

    async def feed(self, update: Update) -> None:
        await self.dp.feed_update(self.bot, update, game=self.game, throttle=self.throttle)


def test_sliding_window():
    clock = FakeMonotonic()
    t = Throttle(limit=2, window=10, clock=clock)
    assert t.allow(1) and t.allow(1)
    assert not t.allow(1)
    assert t.allow(2)  # счётчики у каждого игрока свои
    clock.t += 10
    assert t.allow(1)


async def test_extra_commands_are_ignored(game):
    clock = FakeMonotonic()
    h = ThrottledHarness(game, Throttle(limit=3, window=10, clock=clock))
    for _ in range(5):
        await h.send(1, "/help")
    assert sum(isinstance(c, SendMessage) for c in h.bot.calls) == 3
    clock.t += 11
    await h.send(1, "/help")
    assert sum(isinstance(c, SendMessage) for c in h.bot.calls) == 4


async def test_extra_button_presses_get_toast_and_change_nothing(game):
    clock = FakeMonotonic()
    h = ThrottledHarness(game, Throttle(limit=3, window=10, clock=clock))
    await h.send(1, "/register")
    await h.send(1, "/market")
    await h.press(1, h.button("Вода"))
    buy = h.button("Купить 1")
    await h.press(1, buy)  # 4-е событие — уже лишнее
    assert h.bot.answers()[-1] == (TOO_FAST, False)
    assert (await game.accounts.profile(1)).inventory == {}


async def test_plain_group_messages_are_not_counted(game):
    clock = FakeMonotonic()
    h = ThrottledHarness(game, Throttle(limit=1, window=10, clock=clock))
    for _ in range(5):
        await h.send(1, "просто болтаю в чате")
    await h.send(1, "/help")
    assert sum(isinstance(c, SendMessage) for c in h.bot.calls) == 1
