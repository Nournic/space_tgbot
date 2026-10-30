"""Рейтинги: порядок, равенства по ID, место игрока вне топа, кланы по казне."""

from __future__ import annotations

from app.constants import TOP_LIMIT
from tests.conftest import make_user


async def _set(game, sql: str, params: tuple) -> None:
    async with game.db.transaction() as conn:
        await conn.execute(sql, params)


async def test_balance_top_order_and_ties_by_id(game):
    for uid, balance in ((1, 500), (2, 900), (3, 500), (4, 100)):
        await make_user(game, uid, balance=balance)
    r = await game.rankings.top("balance", 4)
    assert [(row.place, row.entity_id, row.value) for row in r.rows] == [
        (1, 2, 900),
        (2, 1, 500),
        (3, 3, 500),
        (4, 4, 100),
    ]
    assert r.me is None  # игрок уже в топе


async def test_my_place_outside_top(game):
    total = TOP_LIMIT + 3
    for uid in range(1, total + 1):
        await make_user(game, uid, balance=10_000 - uid)  # чем больше id, тем беднее
    r = await game.rankings.top("balance", total)
    assert len(r.rows) == TOP_LIMIT
    assert r.me is not None and (r.me.place, r.me.entity_id) == (total, total)


async def test_xp_and_pve_categories(game):
    await make_user(game, 1)
    await make_user(game, 2)
    await _set(game, "UPDATE users SET xp = 250, level = 3 WHERE user_id = ?", (2,))
    await _set(game, "UPDATE player_stats SET pve_wins = 7 WHERE user_id = ?", (1,))
    xp = await game.rankings.top("xp", 1)
    assert [row.entity_id for row in xp.rows] == [2, 1] and xp.rows[0].extra == "ур. 3"
    pve = await game.rankings.top("pve", 2)
    assert (pve.rows[0].entity_id, pve.rows[0].value) == (1, 7)


async def test_unknown_category_falls_back_to_balance(game):
    await make_user(game, 1)
    assert (await game.rankings.top("hacker'; DROP TABLE users", 1)).category == "balance"


async def test_clans_by_treasury_and_my_clan_place(game):
    clans = TOP_LIMIT + 1
    for uid in range(1, clans + 1):
        await make_user(game, uid, balance=5_000)
        view = await game.clans.create(uid, f"Клан {uid:02d}")
        await game.clans.donate(uid, 100 * (clans + 1 - uid))  # первый клан самый богатый
        assert view.id == uid
    r = await game.rankings.top("clans", clans)
    assert [row.entity_id for row in r.rows] == list(range(1, TOP_LIMIT + 1))
    assert r.me is not None and (r.me.place, r.me.entity_id, r.me.extra) == (clans, clans, "👥 1")
    nobody = await game.rankings.top("clans", 999)
    assert nobody.me is None
