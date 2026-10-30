import pytest

from app.errors import GameError, StaleAction
from tests.conftest import give_items, make_user, snapshot


async def test_quest_progress_capped_and_claim_once(game):
    await make_user(game, 1)
    await give_items(game, 1, water=15)
    await game.economy.sell(1, "water", 15)
    day, quests = await game.quests.today(1)
    q = next(q for q in quests if q.quest_id == "daily_sell")
    assert q.progress == 10 and q.done and not q.claimed
    bal = (await game.accounts.profile(1)).balance
    r = await game.quests.claim(1, "daily_sell")
    assert (r.credits, r.xp, r.balance) == (150, 15, bal + 150)
    with pytest.raises(GameError, match="уже получена"):
        await game.quests.claim(1, "daily_sell")
    p = await game.accounts.profile(1)
    assert p.stats["quests_completed"] == 1


async def test_cannot_claim_unfinished(game):
    await make_user(game, 1)
    before = await snapshot(game, 1)
    with pytest.raises(GameError, match="не выполнено"):
        await game.quests.claim(1, "daily_travel")
    with pytest.raises(GameError):
        await game.quests.claim(1, "daily_unknown")
    assert await snapshot(game, 1) == before


async def test_travel_quest_and_new_day_reset(game, clock):
    await make_user(game, 1)
    await game.travel.travel(1, "mars")
    clock.advance(60)
    await game.travel.travel(1, "earth")
    await game.quests.claim(1, "daily_travel")
    old_token = await game.tokens.issue(1, None, "quests", {"date": "2026-01-15"})
    clock.advance(12 * 3600)  # следующие сутки UTC
    _, quests = await game.quests.today(1)
    assert all(q.progress == 0 and not q.claimed for q in quests)
    with pytest.raises(GameError, match="не выполнено"):
        await game.quests.claim(1, "daily_travel")
    with pytest.raises(StaleAction):  # вчерашняя кнопка
        await game.quests.claim(1, "daily_travel", token=old_token)


async def test_failed_operation_gives_no_quest_progress(game):
    await make_user(game, 1)
    with pytest.raises(GameError):
        await game.economy.sell(1, "water", 5)
    _, quests = await game.quests.today(1)
    assert all(q.progress == 0 for q in quests)


async def test_achievements_granted_once(game):
    await make_user(game, 1)
    await game.economy.buy(1, "water", 1)
    await game.economy.buy(1, "water", 1)
    statuses = {a.achievement_id: a for a in await game.quests.achievements(1)}
    assert statuses["first_trade"].earned and not statuses["merchant_100"].earned
    async with game.db.read() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM user_achievements WHERE user_id = 1")
        assert (await cur.fetchone())[0] == 1


async def test_rich_achievement_and_progress_report(game):
    await make_user(game, 1, balance=9_990)
    await give_items(game, 1, electronics=1)
    r = await game.economy.sell(1, "electronics", 1)
    assert "rich_10000" in r.progress.achievements
    r2 = await game.economy.buy(1, "water", 1)
    assert "rich_10000" not in r2.progress.achievements


async def test_level_up_reported(game):
    await make_user(game, 1)
    async with game.db.transaction() as conn:
        await conn.execute("UPDATE users SET xp = 99 WHERE user_id = 1")
    r = await game.economy.buy(1, "water", 1)
    assert r.progress.leveled_up and r.progress.new_level == 2
    p = await game.accounts.profile(1)
    assert (p.xp, p.level) == (100, 2)
