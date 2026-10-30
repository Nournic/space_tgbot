"""Сборка всех игровых сервисов в один контейнер."""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.clock import Clock, SystemClock
from app.db.connection import Database
from app.services.accounts import AccountService, TokenService
from app.services.base import ServiceContext
from app.services.clans import ClanService
from app.services.combat import CombatService
from app.services.crafting import CraftingService
from app.services.economy import EconomyService
from app.services.events import EventService
from app.services.mining import MiningService
from app.services.offers import OfferService
from app.services.pvp import PvpService
from app.services.quests import QuestService
from app.services.rankings import RankingService
from app.services.ships import ShipService
from app.services.travel import TravelService


@dataclass
class Game:
    ctx: ServiceContext
    accounts: AccountService
    tokens: TokenService
    economy: EconomyService
    events: EventService
    travel: TravelService
    ships: ShipService
    mining: MiningService
    crafting: CraftingService
    combat: CombatService
    pvp: PvpService
    offers: OfferService
    quests: QuestService
    clans: ClanService
    rankings: RankingService

    @property
    def db(self) -> Database:
        return self.ctx.db

    async def cleanup(self):
        """Идемпотентная очистка просроченных объектов. Возвращает уведомления для чатов."""
        notices = await self.pvp.expire_due()
        notices += await self.offers.expire_due()
        async with self.db.transaction() as conn:
            now = self.ctx.clock.now()
            await conn.execute("UPDATE action_tokens SET status = 'expired' WHERE status = 'active' AND expires_at <= ?",
                               (now,))
            await conn.execute("DELETE FROM action_tokens WHERE status <> 'active' AND expires_at <= ?",
                               (now - 86_400,))
        return notices


def build_game(db: Database, *, seed: str, clock: Clock | None = None, rng: random.Random | None = None) -> Game:
    ctx = ServiceContext(db=db, clock=clock or SystemClock(), rng=rng or random.SystemRandom(), seed=seed)
    return Game(
        ctx=ctx,
        accounts=AccountService(ctx),
        tokens=TokenService(ctx),
        economy=EconomyService(ctx),
        events=EventService(ctx),
        travel=TravelService(ctx),
        ships=ShipService(ctx),
        mining=MiningService(ctx),
        crafting=CraftingService(ctx),
        combat=CombatService(ctx),
        pvp=PvpService(ctx),
        offers=OfferService(ctx),
        quests=QuestService(ctx),
        clans=ClanService(ctx),
        rankings=RankingService(ctx),
    )
