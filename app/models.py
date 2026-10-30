"""Типизированные DTO и результаты сервисов (без зависимостей от Telegram)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.constants import (
    ARMOR_HP_PER_LEVEL,
    CARGO_PER_LEVEL,
    ENERGY_REGEN_SECONDS,
    MAX_ENERGY,
    SHIP_CLASSES,
)


def ship_max_hp(ship_class: str, armor_level: int) -> int:
    return SHIP_CLASSES[ship_class].hp + ARMOR_HP_PER_LEVEL * armor_level


def ship_capacity(ship_class: str, cargo_level: int) -> int:
    return SHIP_CLASSES[ship_class].cargo + CARGO_PER_LEVEL * cargo_level


@dataclass
class ShipState:
    user_id: int
    ship_class: str
    cargo_level: int
    engine_level: int
    weapon_level: int
    armor_level: int
    hp: int
    energy: int
    energy_anchor: int
    travel_cooldown_until: int
    mine_cooldown_until: int
    hunt_cooldown_until: int

    @property
    def max_hp(self) -> int:
        return ship_max_hp(self.ship_class, self.armor_level)

    @property
    def capacity(self) -> int:
        return ship_capacity(self.ship_class, self.cargo_level)

    @property
    def class_name(self) -> str:
        return SHIP_CLASSES[self.ship_class].name

    def module_level(self, module: str) -> int:
        return int(getattr(self, f"{module}_level"))

    def seconds_to_next_energy(self, now: int) -> int | None:
        if self.energy >= MAX_ENERGY:
            return None
        return max(0, self.energy_anchor + ENERGY_REGEN_SECONDS - now)


@dataclass
class Profile:
    user_id: int
    display_name: str
    balance: int
    planet_id: str
    xp: int
    level: int
    ship: ShipState
    inventory: dict[str, int]
    reserved: dict[str, int]
    cargo_used: int
    clan_name: str | None
    stats: dict[str, int]
    created_at: int


@dataclass
class RegisterResult:
    created: bool
    profile: Profile


@dataclass
class Progress:
    """Побочные эффекты прогрессии, накопленные за одну операцию."""

    xp_gained: int = 0
    old_level: int = 0
    new_level: int = 0
    achievements: list[str] = field(default_factory=list)
    quests_completed: list[str] = field(default_factory=list)

    @property
    def leveled_up(self) -> bool:
        return self.new_level > self.old_level

    def merge_level(self, old: int, new: int, xp: int) -> None:
        if self.old_level == 0:
            self.old_level = old
        self.new_level = new
        self.xp_gained += xp


@dataclass
class TradeResult:
    op: str  # buy | sell
    item_id: str
    quantity: int
    unit_price: int
    total: int
    balance: int
    cargo_used: int
    capacity: int
    owned: int
    progress: Progress


@dataclass
class TravelResult:
    from_planet: str
    to_planet: str
    energy_cost: int
    energy_left: int
    cooldown_until: int
    progress: Progress


@dataclass
class MineResult:
    item_id: str
    quantity: int
    energy_left: int
    cargo_used: int
    capacity: int
    progress: Progress


@dataclass
class CraftResult:
    item_id: str
    quantity: int
    fee: int
    consumed: dict[str, int]
    balance: int
    progress: Progress


@dataclass
class HuntResult:
    enemy_id: str
    player_power: int
    enemy_power: int
    won: bool
    reward: int
    damage: int
    hp_left: int
    max_hp: int
    energy_left: int
    progress: Progress


@dataclass
class UpgradeResult:
    module: str
    new_level: int
    cost: int
    balance: int


@dataclass
class ShipPurchaseResult:
    ship_class: str
    cost: int
    balance: int
    hp: int
    capacity: int


@dataclass
class RepairResult:
    repaired: int
    cost: int
    hp: int
    max_hp: int
    balance: int


@dataclass
class OfferView:
    id: int
    seller_id: int
    seller_name: str
    buyer_id: int
    buyer_name: str
    item_id: str
    quantity: int
    price: int
    status: str
    created_at: int
    expires_at: int
    chat_id: int | None = None
    message_id: int | None = None


@dataclass
class OfferOutcome:
    """Результат действия с предложением. status — итоговый статус оффера."""

    offer: OfferView
    status: str
    seller_progress: Progress | None = None
    buyer_progress: Progress | None = None


@dataclass
class ChallengeView:
    id: int
    challenger_id: int
    challenger_name: str
    target_id: int
    target_name: str
    stake: int
    status: str
    created_at: int
    expires_at: int
    chat_id: int | None = None
    message_id: int | None = None
    winner_id: int | None = None


@dataclass
class DuelResult:
    challenge: ChallengeView
    status: str  # resolved | expired
    challenger_power: int = 0
    target_power: int = 0
    winner_id: int | None = None  # None — ничья
    challenger_damage: int = 0
    target_damage: int = 0
    challenger_hp: int = 0
    target_hp: int = 0
    challenger_xp: int = 0
    target_xp: int = 0
    xp_capped: bool = False
    challenger_progress: Progress | None = None
    target_progress: Progress | None = None


@dataclass
class QuestView:
    quest_id: str
    progress: int
    target: int
    claimed: bool

    @property
    def done(self) -> bool:
        return self.progress >= self.target


@dataclass
class ClaimResult:
    quest_id: str
    credits: int
    xp: int
    balance: int
    progress: Progress


@dataclass
class ClanView:
    id: int
    name: str
    leader_id: int
    leader_name: str
    treasury: int
    is_open: bool
    member_count: int
    created_at: int
    members: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class RankRow:
    place: int
    entity_id: int
    name: str
    value: int
    extra: str = ""


@dataclass
class Ranking:
    category: str
    rows: list[RankRow]
    me: RankRow | None


@dataclass
class LedgerEntry:
    id: int
    kind: str
    amount: int
    balance_after: int
    item_id: str | None
    quantity: int | None
    details: str | None
    created_at: int


@dataclass
class HistoryPage:
    entries: list[LedgerEntry]
    page: int
    pages: int
    total: int


@dataclass
class AchievementStatus:
    achievement_id: str
    earned: bool
    current: int
    target: int
    earned_at: int | None


@dataclass
class ExpiredNotice:
    kind: str  # offer | challenge
    id: int
    chat_id: int | None
    message_id: int | None
    text: str


__all__ = [
    "MAX_ENERGY",
    "ShipState",
    "ship_max_hp",
    "ship_capacity",
    "Profile",
    "RegisterResult",
    "Progress",
    "TradeResult",
    "TravelResult",
    "MineResult",
    "CraftResult",
    "HuntResult",
    "UpgradeResult",
    "ShipPurchaseResult",
    "RepairResult",
    "OfferView",
    "OfferOutcome",
    "ChallengeView",
    "DuelResult",
    "QuestView",
    "ClaimResult",
    "ClanView",
    "RankRow",
    "Ranking",
    "LedgerEntry",
    "HistoryPage",
    "AchievementStatus",
    "ExpiredNotice",
]
