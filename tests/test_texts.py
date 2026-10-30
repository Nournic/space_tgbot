"""Числа в текстах бота берутся из app/constants.py, а не дублируются."""

from __future__ import annotations

from app.bot.formatting import clan_text, recipes_text
from app.bot.handlers.common import HELP_TEXT
from app.constants import (
    CLAN_MAX_MEMBERS,
    CRAFT_FEE_PER_UNIT,
    HUNT_ENERGY,
    MAX_ENERGY,
    MINE_ENERGY,
    MODULE_COST_STEP,
    XP_CRAFT,
)
from app.models import ClanView
from tests.test_handlers import Harness


def test_static_texts_use_constants():
    assert f"({MINE_ENERGY} 🔋)" in HELP_TEXT and f"({HUNT_ENERGY} 🔋)" in HELP_TEXT
    assert f"+{XP_CRAFT} XP" in recipes_text()
    view = ClanView(1, "Орион", 1, "Лидер", 0, True, 3, 0)
    assert f"3/{CLAN_MAX_MEMBERS}" in clan_text(view)


async def test_rendered_texts_use_constants(game):
    h = Harness(game)
    await h.send(1, "/register")
    await h.send(1, "/upgrade")
    assert f"{MODULE_COST_STEP} × n" in h.bot.texts()[-1]
    await h.send(1, "/map")
    assert f"/{MAX_ENERGY}" in h.bot.texts()[-1]
    await h.send(1, "/craft fuel_cell 3")
    assert f"работа {CRAFT_FEE_PER_UNIT * 3} кр." in h.bot.texts()[-1]
