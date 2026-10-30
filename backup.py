"""Онлайн-резервная копия SQLite (безопасна при работающем боте, учитывает WAL).

Использование:
    python backup.py                     # → backups/space_trader-YYYYmmdd-HHMMSS.sqlite3
    python backup.py путь/к/копии.sqlite3
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv


def backup(source: str, target: str) -> str:
    if not os.path.exists(source):
        raise SystemExit(f"База {source} не найдена")
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    src = sqlite3.connect(source, timeout=30)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)                                  # постраничная консистентная копия
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"Проверка копии не пройдена: {result}")
    finally:
        dst.close()
        src.close()
    return target


def main() -> None:
    load_dotenv()
    source = os.getenv("DATABASE_PATH", "data/space_trader.sqlite3")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join("backups", f"space_trader-{stamp}.sqlite3")
    print(f"Резервная копия создана: {backup(source, target)}")


if __name__ == "__main__":
    main()
