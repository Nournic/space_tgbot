import asyncio

import pytest

from app.errors import GameError, InsufficientFunds, NotYourButton, StaleAction, ValidationError
from tests.conftest import make_user


async def test_create_and_unique_name(game):
    await make_user(game, 1)
    await make_user(game, 2)
    v = await game.clans.create(1, "  Звёздные   Волки ")
    assert v.name == "Звёздные Волки" and v.member_count == 1 and v.is_open
    assert (await game.accounts.profile(1)).balance == 0
    await make_user(game, 3, balance=5000)
    with pytest.raises(GameError, match="уже существует"):
        await game.clans.create(3, "звёздные волки")
    await make_user(game, 4, balance=999)
    with pytest.raises(InsufficientFunds):
        await game.clans.create(4, "Другие")
    assert await game.clans.my_clan_id(4) is None
    for bad in ("ab", "x" * 33, "<script>"):
        with pytest.raises(ValidationError):
            await game.clans.create(3, bad)


async def test_join_leave_donate(game):
    await make_user(game, 1)
    await make_user(game, 2)
    v = await game.clans.create(1, "Альфа")
    await game.clans.join(2, v.id)
    with pytest.raises(GameError, match="уже состоите"):
        await game.clans.join(2, v.id)
    view, bal = await game.clans.donate(2, 300)
    assert view.treasury == 300 and bal == 700
    with pytest.raises(InsufficientFunds):
        await game.clans.donate(2, 701)
    with pytest.raises(ValidationError):
        await game.clans.donate(2, 0)
    with pytest.raises(GameError, match="Лидер не может"):
        await game.clans.leave(1)
    assert await game.clans.leave(2) == "Альфа"
    assert (await game.clans.info(1)).member_count == 1


async def test_member_limit_30_under_concurrency(game):
    await make_user(game, 1)
    v = await game.clans.create(1, "Большой клан")
    for uid in range(2, 41):
        await make_user(game, uid)
    results = await asyncio.gather(*(game.clans.join(uid, v.id) for uid in range(2, 41)), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 29
    assert (await game.clans.info(1)).member_count == 30


async def test_transfer_and_disband(game):
    await make_user(game, 1)
    await make_user(game, 2)
    await make_user(game, 3)
    v = await game.clans.create(1, "Бета")
    await game.clans.join(2, v.id)
    with pytest.raises(GameError, match="только лидер"):
        await game.clans.transfer(2, 1)
    with pytest.raises(GameError, match="не состоит"):
        await game.clans.transfer(1, 3)
    v = await game.clans.transfer(1, 2)
    assert v.leader_id == 2
    await game.clans.leave(1)                               # бывший лидер теперь может выйти
    await game.clans.donate(2, 500)
    await game.clans.join(3, v.id)
    with pytest.raises(GameError, match="только лидер"):
        await game.clans.disband(3)
    token = await game.tokens.issue(2, None, "clan_disband", {"clan_id": v.id})
    with pytest.raises(NotYourButton):
        await game.clans.disband(1, token=token)
    gone = await game.clans.disband(2, token=token)
    assert gone.treasury == 500
    with pytest.raises(StaleAction):
        await game.clans.disband(2, token=token)
    assert await game.clans.my_clan_id(2) is None
    assert (await game.accounts.profile(2)).balance == 500   # казна сгорела, взнос не вернулся
    clans, _, _ = await game.clans.list_open()
    assert clans == []
