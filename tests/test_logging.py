"""Токен бота не попадает в логи."""

from __future__ import annotations

import logging

from main import _TokenFilter

TOKEN = "123456:SECRET-TOKEN"


def _record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord("x", logging.INFO, __file__, 1, msg, args, None)


def test_token_masked_in_formatted_message():
    record = _record("GET https://api.telegram.org/bot%s/getMe", TOKEN)
    assert _TokenFilter(TOKEN).filter(record) is True
    assert TOKEN not in record.getMessage() and "***" in record.getMessage()


def test_message_without_token_untouched():
    record = _record("обычное сообщение %s", 42)
    _TokenFilter(TOKEN).filter(record)
    assert record.getMessage() == "обычное сообщение 42"
