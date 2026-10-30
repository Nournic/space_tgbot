"""Загрузка настроек из окружения / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: str
    game_seed: str
    log_level: str


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "your_bot_token_here":
        raise RuntimeError("BOT_TOKEN не задан. Скопируйте .env.example в .env и укажите токен от @BotFather.")
    return Settings(
        bot_token=token,
        database_path=os.getenv("DATABASE_PATH", "data/space_trader.sqlite3").strip() or "data/space_trader.sqlite3",
        game_seed=os.getenv("GAME_SEED", "space-trader-1.0").strip() or "space-trader-1.0",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
