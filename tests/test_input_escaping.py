"""Ввод игрока, попадающий в текст ответа, экранируется (ответы уходят с parse_mode=HTML)."""

from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.services.crafting import validate_recipe
from app.services.economy import validate_item
from tests.test_handlers import Harness


@pytest.mark.parametrize("validate", [validate_item, validate_recipe])
def test_service_errors_escape_raw_input(validate):
    with pytest.raises(ValidationError) as exc:
        validate("<b>x</b>")
    assert "<b>" not in exc.value.message
    assert "&lt;b&gt;x" in exc.value.message


async def test_craft_with_markup_gets_safe_answer(game):
    h = Harness(game)
    await h.send(1, "/register")
    await h.send(1, '/craft <a href="x">y</a>')
    answer = h.bot.texts()[-1]
    assert "Нет рецепта" in answer
    assert "<a" not in answer
