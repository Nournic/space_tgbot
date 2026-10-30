@AGENTS.md

## Заметки для Claude Code

- Проверяй изменения командой `pytest -q` (на Windows: `.venv\Scripts\python -m pytest -q`), затем `ruff check .` и `ruff format --check .`.
- Перед изменением схемы БД перечитай раздел «Миграции» выше.
- Общие разрешения лежат в `.claude/settings.json`. Личные настройки — в `.claude/settings.local.json`, этот файл не коммитится.
