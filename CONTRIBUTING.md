# Как работать над проектом

Над Space Trader работают несколько разработчиков, и почти у каждого есть ИИ-агент (Claude Code, Codex). Правила для агентов лежат в [AGENTS.md](AGENTS.md), этот файл — для людей.

## Первый запуск

```bash
git clone <url> space_tgbot && cd space_tgbot
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

В `.env` укажите токен **своего тестового бота**: создайте его у @BotFather. Продовый токен и продовый `GAME_SEED` разработчикам не нужны. Тестовая база создаётся в `data/` автоматически.

```bash
pytest -q
python main.py
```

## Процесс

1. **Issue.** Задача описывается по шаблону «Задача»: цель, затронутые файлы, критерии готовности. Хорошо описанную задачу можно целиком отдать агенту.
2. **Ветка от свежего `main`:** `feat/…`, `fix/…`, `chore/…` или `docs/…`. Одна задача — одна ветка.
3. **Коммиты** в формате Conventional Commits, маленькие. Форматирование ruff не смешивается с логикой.
4. **PR** по шаблону. Укажите, участвовал ли ИИ. Автор PR читает весь diff, включая код агента, и отвечает за него.
5. **CI** должен быть зелёным: ruff lint, ruff format, pytest на Python 3.11 и 3.12, сборка Docker.
6. **Ревью** — минимум одно одобрение человека. Изменения в `app/services/`, `app/db/` и `app/constants.py` (деньги, баланс, схема) смотрим особенно внимательно.
7. **Merge** — только squash merge. Ветка удаляется автоматически.

## Работа с ИИ-агентами

- Claude Code читает `CLAUDE.md`, который импортирует `AGENTS.md`. Codex читает `AGENTS.md` напрямую. Правила меняются только в `AGENTS.md`.
- Общие разрешения Claude Code лежат в `.claude/settings.json`. Тесты и ruff запускаются без подтверждений, а `.env`, `data/`, `deploy.sh`, `ssh`/`scp` и force-push запрещены. Личные настройки пишите в `.claude/settings.local.json`, он в `.gitignore`.
- Codex: sandbox и режим подтверждений каждый настраивает у себя, локальная папка `.codex/` в `.gitignore`. Рекомендуемый режим — запись только в рабочей папке и подтверждение сетевых команд.
- Агент не мержит PR, не пушит в `main` и не деплоит.
- Если в одном клоне параллельно работают несколько агентов, у каждого должен быть свой worktree, иначе они перезапишут файлы друг друга:

  ```bash
  git worktree add ../st-feat-market -b feat/market-filters
  ```

- Перед тем как отдать задачу агенту, укажите в ней, что нельзя менять: баланс, формат `callback_data`, схему.

## Миграции БД

- `V1` уже применена на проде, её не трогаем. Любое изменение схемы оформляется новой записью в `MIGRATIONS` (`app/db/migrations.py`).
- Если после rebase на `main` ваш номер миграции уже занят, перенумеруйте свою на следующий свободный. Тест `test_migration_versions_are_contiguous` упадёт, если номера пересеклись.
- Миграция должна работать на базе с живыми данными: добавлять столбцы с `DEFAULT`, без потери строк.

## Деплой

Только мейнтейнер, после merge в `main`:

```bash
git checkout main && git pull && ./deploy.sh
```

Подробности — в README → «Деплой на VPS».

## Настройки GitHub (один раз, вручную)

- [ ] Settings → Branches → правило для `main`:
  - [ ] Require a pull request before merging, 1 approval
  - [ ] Require status checks: `lint & tests (py3.11)`, `lint & tests (py3.12)`, `docker build`
  - [ ] Block force pushes, запретить удаление ветки
- [ ] Settings → General → Pull Requests: разрешить только «Squash merging» и включить «Automatically delete head branches».
- [ ] Вписать логин мейнтейнера в `.github/CODEOWNERS` и включить «Require review from Code Owners».
