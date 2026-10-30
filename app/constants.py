"""Централизованный игровой контент и баланс «Космического Трейдера 1.0».

Все числа взяты из технического задания. Значения неизменяемы во время работы.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# --------------------------------------------------------------------------- старт
START_BALANCE = 1_000
START_PLANET = "earth"
START_SHIP = "shuttle"

# --------------------------------------------------------------------------- лимиты
MAX_QTY = 10_000  # максимум единиц товара в одной операции
MAX_CRAFT_QTY = 1_000  # максимум производств за одну команду
MAX_PRICE = 10_000_000  # максимум цены P2P-предложения
MAX_STAKE = 1_000_000  # максимум ставки PvP
MAX_DONATE = 10_000_000  # максимум одного взноса в казну
DISPLAY_NAME_MAX = 64
HISTORY_PAGE_SIZE = 10
TOP_LIMIT = 10
CLAN_PAGE_SIZE = 10
PRICES_PAGE_SIZE = 4  # товаров на одной странице /prices

# --------------------------------------------------------------------------- энергия/время
MAX_ENERGY = 100
ENERGY_REGEN_SECONDS = 300  # 1 энергия за 5 полных минут
TRAVEL_COOLDOWN = 60
TRAVEL_MIN_COST = 5
HUNT_ENERGY = 15
HUNT_COOLDOWN = 30
MINE_ENERGY = 12
MINE_COOLDOWN = 30
PVP_ENERGY = 10
OFFER_TTL = 300
CHALLENGE_TTL = 300
TOKEN_TTL = 900  # время жизни одноразовой inline-клавиатуры
PVP_XP_PAIR_COOLDOWN = 3600
FLOOD_MAX_ACTIONS = 5  # антифлуд: не больше 5 команд/нажатий одного игрока…
FLOOD_WINDOW_SECONDS = 10  # …за 10 секунд

# --------------------------------------------------------------------------- XP
XP_PER_LEVEL = 100
XP_TRADE = 1
XP_TRAVEL = 2
XP_MINE = 3
XP_CRAFT = 2
XP_PVE_LOSS = 5
XP_PVP_WIN = 20
XP_PVP_LOSS = 5
XP_PVP_DRAW = 3


def level_for_xp(xp: int) -> int:
    return 1 + xp // XP_PER_LEVEL


# --------------------------------------------------------------------------- планеты
@dataclass(frozen=True)
class Planet:
    id: str
    name: str
    emoji: str
    description: str

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


PLANETS: Mapping[str, Planet] = MappingProxyType(
    {
        "earth": Planet("earth", "Земля", "🌍", "Стартовая торговая планета"),
        "mars": Planet("mars", "Марс", "🔴", "Руда и промышленность"),
        "ceres": Planet("ceres", "Церера", "☄️", "Минералы и добыча"),
        "venus": Planet("venus", "Венера", "🟡", "Дорогие технологии"),
        "europa": Planet("europa", "Европа", "🧊", "Вода и химические ресурсы"),
        "titan": Planet("titan", "Титан", "🪐", "Редкие материалы, опасные маршруты"),
    }
)
PLANET_ORDER = ("earth", "mars", "ceres", "venus", "europa", "titan")

_ROUTE_LIST = (
    ("earth", "mars", 10),
    ("earth", "venus", 8),
    ("mars", "ceres", 12),
    ("mars", "europa", 18),
    ("venus", "ceres", 16),
    ("ceres", "europa", 12),
    ("europa", "titan", 22),
)


def _build_routes() -> dict[str, dict[str, int]]:
    routes: dict[str, dict[str, int]] = {p: {} for p in PLANET_ORDER}
    for a, b, cost in _ROUTE_LIST:
        routes[a][b] = cost
        routes[b][a] = cost
    return routes


ROUTES: Mapping[str, Mapping[str, int]] = MappingProxyType({k: MappingProxyType(v) for k, v in _build_routes().items()})


# --------------------------------------------------------------------------- товары
@dataclass(frozen=True)
class Item:
    id: str
    name: str
    emoji: str
    weight: int

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


ITEMS: Mapping[str, Item] = MappingProxyType(
    {
        "water": Item("water", "Вода", "💧", 1),
        "iron": Item("iron", "Железо", "⛓️", 1),
        "spice": Item("spice", "Спайс", "✨", 1),
        "silicon": Item("silicon", "Кремний", "🪨", 1),
        "titanium": Item("titanium", "Титан", "🔩", 2),
        "fuel_cell": Item("fuel_cell", "Энергоячейка", "🔋", 1),
        "electronics": Item("electronics", "Электроника", "💻", 2),
        "medicine": Item("medicine", "Медикаменты", "💊", 1),
    }
)
ITEM_ORDER = ("water", "iron", "spice", "silicon", "titanium", "fuel_cell", "electronics", "medicine")

_PRICE_ROWS = {
    "earth": (10, 25, 80, 40, 70, 65, 125, 110),
    "mars": (18, 15, 95, 35, 55, 80, 145, 135),
    "ceres": (25, 10, 75, 20, 45, 90, 160, 150),
    "venus": (16, 32, 115, 55, 85, 55, 95, 120),
    "europa": (7, 40, 90, 60, 100, 75, 150, 95),
    "titan": (32, 28, 60, 48, 25, 120, 180, 165),
}
BASE_PRICES: Mapping[str, Mapping[str, int]] = MappingProxyType(
    {planet: MappingProxyType(dict(zip(ITEM_ORDER, row, strict=True))) for planet, row in _PRICE_ROWS.items()}
)

DAILY_DEVIATION_PCT = 20  # ±20% ежедневно
EVENT_MAX_PCT = 10  # ±10% от события
PRICE_MIN_PCT = 70
PRICE_MAX_PCT = 130
SELL_RATIO_PCT = 90

# --------------------------------------------------------------------------- добыча
MINEABLE: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "earth": ("water", "iron"),
        "mars": ("iron", "silicon"),
        "ceres": ("iron", "silicon", "titanium"),
        "venus": ("silicon", "spice"),
        "europa": ("water", "silicon"),
        "titan": ("titanium", "spice"),
    }
)
MINE_MIN_UNITS = 1
MINE_MAX_UNITS = 4

# --------------------------------------------------------------------------- рецепты
RECIPES: Mapping[str, Mapping[str, int]] = MappingProxyType(
    {
        "fuel_cell": MappingProxyType({"water": 2, "silicon": 1}),
        "electronics": MappingProxyType({"iron": 2, "silicon": 2}),
        "medicine": MappingProxyType({"water": 2, "spice": 1}),
    }
)
CRAFT_FEE_PER_UNIT = 10


# --------------------------------------------------------------------------- корабли
@dataclass(frozen=True)
class ShipClass:
    id: str
    name: str
    price: int | None  # None — нельзя купить (стартовый)
    cargo: int
    hp: int
    min_level: int
    combat_bonus: int


SHIP_CLASSES: Mapping[str, ShipClass] = MappingProxyType(
    {
        "shuttle": ShipClass("shuttle", "Шаттл", None, 20, 100, 1, 0),
        "scout": ShipClass("scout", "Разведчик", 2_500, 30, 110, 3, 2),
        "freighter": ShipClass("freighter", "Грузовик", 6_000, 65, 140, 6, 0),
        "corvette": ShipClass("corvette", "Корвет", 10_000, 45, 190, 10, 6),
    }
)
SHIP_ORDER = ("shuttle", "scout", "freighter", "corvette")

MODULES: Mapping[str, str] = MappingProxyType(
    {
        "cargo": "📦 Грузовой отсек",
        "engine": "🚀 Двигатель",
        "weapon": "🔫 Оружие",
        "armor": "🛡 Броня",
    }
)
MODULE_ORDER = ("cargo", "engine", "weapon", "armor")
MODULE_MAX_LEVEL = 5
MODULE_COST_STEP = 500  # стоимость перехода на уровень n = 500 × n
CARGO_PER_LEVEL = 10
WEAPON_PER_LEVEL = 4
ARMOR_HP_PER_LEVEL = 25
ARMOR_DAMAGE_REDUCTION = 2
REPAIR_COST_PER_HP = 5


# --------------------------------------------------------------------------- пираты
@dataclass(frozen=True)
class Enemy:
    id: str
    name: str
    power_min: int
    power_max: int
    reward_min: int
    reward_max: int
    xp: int


ENEMIES: Mapping[str, Enemy] = MappingProxyType(
    {
        "raider": Enemy("raider", "Мародёр", 10, 22, 60, 100, 15),
        "scout_pirate": Enemy("scout_pirate", "Пиратский разведчик", 18, 32, 100, 160, 20),
        "frigate": Enemy("frigate", "Пиратский фрегат", 27, 44, 180, 280, 30),
    }
)
ENEMY_ORDER = ("raider", "scout_pirate", "frigate")
# Вес встречи (raider, scout_pirate, frigate) по планетам: дальние планеты опаснее.
ENEMY_WEIGHTS: Mapping[str, tuple[int, int, int]] = MappingProxyType(
    {
        "earth": (70, 25, 5),
        "mars": (50, 35, 15),
        "venus": (50, 35, 15),
        "ceres": (35, 40, 25),
        "europa": (30, 40, 30),
        "titan": (15, 35, 50),
    }
)
PLAYER_BASE_POWER = 10
POWER_ROLL_MIN = 1
POWER_ROLL_MAX = 20
PVE_WIN_DAMAGE = (5, 12)
PVE_LOSS_DAMAGE = (20, 40)
PVP_LOSER_DAMAGE = (20, 35)
PVP_WINNER_DAMAGE = (0, 10)
PVP_DEFENSE_PER_ARMOR = 2


# --------------------------------------------------------------------------- квесты
@dataclass(frozen=True)
class Quest:
    id: str
    title: str
    target: int
    reward_credits: int
    reward_xp: int


QUESTS: Mapping[str, Quest] = MappingProxyType(
    {
        "daily_sell": Quest("daily_sell", "Продать 10 единиц товаров системному рынку", 10, 150, 15),
        "daily_travel": Quest("daily_travel", "Выполнить 2 успешных перелёта", 2, 100, 10),
        "daily_mine": Quest("daily_mine", "Добыть 5 единиц ресурсов", 5, 120, 12),
        "daily_pirate": Quest("daily_pirate", "Победить 1 пирата", 1, 200, 20),
    }
)
QUEST_ORDER = ("daily_sell", "daily_travel", "daily_mine", "daily_pirate")


# --------------------------------------------------------------------------- достижения
@dataclass(frozen=True)
class Achievement:
    id: str
    title: str
    description: str
    stat: str  # поле player_stats или "balance"
    target: int


ACHIEVEMENTS: Mapping[str, Achievement] = MappingProxyType(
    {
        "first_trade": Achievement("first_trade", "🛍 Первая сделка", "1 успешная рыночная операция", "trades", 1),
        "merchant_100": Achievement("merchant_100", "💼 Торговец", "100 успешных сделок", "trades", 100),
        "traveler_10": Achievement("traveler_10", "🚀 Путешественник", "10 перелётов", "travels", 10),
        "miner_100": Achievement("miner_100", "⛏ Старатель", "100 добытых ресурсов", "units_mined", 100),
        "pirate_hunter_10": Achievement("pirate_hunter_10", "☠️ Гроза пиратов", "10 побед в PvE", "pve_wins", 10),
        "pvp_10": Achievement("pvp_10", "⚔️ Дуэлянт", "10 побед в PvP", "pvp_wins", 10),
        "rich_10000": Achievement(
            "rich_10000", "💰 Богач", "Иметь 10 000 кредитов на доступном балансе", "balance", 10_000
        ),
        "crafter_25": Achievement("crafter_25", "🛠 Инженер", "25 успешных производств", "crafts", 25),
    }
)
ACHIEVEMENT_ORDER = (
    "first_trade",
    "merchant_100",
    "traveler_10",
    "miner_100",
    "pirate_hunter_10",
    "pvp_10",
    "rich_10000",
    "crafter_25",
)

# --------------------------------------------------------------------------- статистика
STAT_FIELDS = (
    "trades",
    "units_bought",
    "units_sold",
    "travels",
    "units_mined",
    "crafts",
    "pve_wins",
    "pve_losses",
    "pvp_wins",
    "pvp_losses",
    "pvp_draws",
    "quests_completed",
    "credits_earned",
)


# --------------------------------------------------------------------------- события
@dataclass(frozen=True)
class WorldEvent:
    id: str
    title: str
    description: str
    modifiers: Mapping[str, int]  # item_id -> процент к цене покупки


WORLD_EVENTS: Mapping[str, WorldEvent] = MappingProxyType(
    {
        "quiet": WorldEvent("quiet", "Спокойный сектор", "Без дополнительных модификаторов цен.", MappingProxyType({})),
        "water_shortage": WorldEvent(
            "water_shortage",
            "Дефицит воды",
            "+10% к цене покупки воды на всех планетах.",
            MappingProxyType({"water": 10}),
        ),
        "industrial_boom": WorldEvent(
            "industrial_boom",
            "Промышленный бум",
            "+10% к цене покупки железа и кремния.",
            MappingProxyType({"iron": 10, "silicon": 10}),
        ),
        "spice_glut": WorldEvent(
            "spice_glut", "Избыток спайса", "−10% к цене покупки спайса.", MappingProxyType({"spice": -10})
        ),
        "tech_rush": WorldEvent(
            "tech_rush",
            "Технологическая гонка",
            "+10% к цене покупки электроники.",
            MappingProxyType({"electronics": 10}),
        ),
    }
)
EVENT_ORDER = ("quiet", "water_shortage", "industrial_boom", "spice_glut", "tech_rush")

# --------------------------------------------------------------------------- кланы
CLAN_CREATE_COST = 1_000
CLAN_MAX_MEMBERS = 30
CLAN_NAME_MIN = 3
CLAN_NAME_MAX = 32
