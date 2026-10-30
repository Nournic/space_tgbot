"""Корабль и ресурсы: /ship, /shipyard, /upgrade, /repair, /mine, /recipes, /craft."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.formatting import esc, item_title, progress_lines, recipes_text, ship_text, shipyard_text
from app.bot.keyboards import shipyard_kb, single_action_kb, upgrade_kb
from app.bot.utils import parse_int, split_args
from app.constants import (
    MAX_CRAFT_QTY,
    MINE_ENERGY,
    MODULE_MAX_LEVEL,
    MODULE_ORDER,
    MODULES,
    RECIPES,
    REPAIR_COST_PER_HP,
    SHIP_CLASSES,
)
from app.errors import ValidationError
from app.models import CraftResult, MineResult, RepairResult, ShipPurchaseResult, UpgradeResult
from app.services import Game
from app.services.crafting import validate_recipe
from app.services.ships import upgrade_cost

router = Router(name="ship")


@router.message(Command("ship"))
async def cmd_ship(message: Message, game: Game) -> None:
    p = await game.accounts.profile(message.from_user.id)
    await message.answer(ship_text(p, game.ctx.clock.now()) + "\n\n/upgrade · /repair · /shipyard")


# ----------------------------------------------------------------- верфь
def purchase_text(r: ShipPurchaseResult) -> str:
    return (
        f"🚀 Новый корпус «<b>{SHIP_CLASSES[r.ship_class].name}</b>» за {r.cost} кр.!\n"
        f"❤️ HP {r.hp}, 📦 трюм {r.capacity}, 💰 баланс {r.balance}"
    )


async def render_shipyard(game: Game, user_id: int, chat_id: int | None):
    p = await game.accounts.profile(user_id)
    token = await game.tokens.issue(user_id, chat_id, "shipyard")
    return shipyard_text(p), shipyard_kb(token, p.ship.ship_class)


@router.message(Command("shipyard"))
async def cmd_shipyard(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if args:
        result = await game.ships.buy_ship(message.from_user.id, args[0])
        await message.answer(purchase_text(result))
        return
    text, kb = await render_shipyard(game, message.from_user.id, message.chat.id)
    await message.answer(text, reply_markup=kb)


# ----------------------------------------------------------------- модули
def upgrade_text(r: UpgradeResult) -> str:
    return f"🔧 {MODULES[r.module]} улучшен до уровня <b>{r.new_level}</b> за {r.cost} кр. Баланс: {r.balance}"


async def render_upgrades(game: Game, user_id: int, chat_id: int | None, prefix: str = ""):
    p = await game.accounts.profile(user_id)
    levels = {m: p.ship.module_level(m) for m in MODULE_ORDER}
    costs = {m: upgrade_cost(levels[m] + 1) for m in MODULE_ORDER if levels[m] < MODULE_MAX_LEVEL}
    lines = [
        prefix + "🔧 <b>Улучшения модулей</b> (уровни 0–5, переход на n стоит 500 × n)",
        f"💰 Баланс: {p.balance}",
        "",
        f"{MODULES['cargo']}: {levels['cargo']} (+10 трюма/ур.)",
        f"{MODULES['engine']}: {levels['engine']} (−1 энергии перелёта/ур., минимум 5)",
        f"{MODULES['weapon']}: {levels['weapon']} (+4 к силе/ур.)",
        f"{MODULES['armor']}: {levels['armor']} (+25 макс. HP и −2 урона/ур.)",
        "",
        "Команда: <code>/upgrade engine</code>",
    ]
    token = await game.tokens.issue(user_id, chat_id, "upgrade")
    return "\n".join(lines), upgrade_kb(token, levels, costs)


@router.message(Command("upgrade"))
async def cmd_upgrade(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if args:
        result = await game.ships.upgrade(message.from_user.id, args[0])
        await message.answer(upgrade_text(result))
        return
    text, kb = await render_upgrades(game, message.from_user.id, message.chat.id)
    await message.answer(text, reply_markup=kb)


# ----------------------------------------------------------------- ремонт
def repair_text(r: RepairResult) -> str:
    return f"🛠 Отремонтировано +{r.repaired} HP за {r.cost} кр. ❤️ {r.hp}/{r.max_hp}, 💰 {r.balance}"


@router.message(Command("repair"))
async def cmd_repair(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    uid = message.from_user.id
    if args:
        amount = None if args[0].lower() in ("full", "все", "всё") else parse_int(args[0], "количество HP", 1, 10_000)
        result = await game.ships.repair(uid, amount)
        await message.answer(repair_text(result))
        return
    p = await game.accounts.profile(uid)
    missing = p.ship.max_hp - p.ship.hp
    if missing <= 0:
        await message.answer(f"✅ Корабль исправен: ❤️ {p.ship.hp}/{p.ship.max_hp}")
        return
    cost = missing * REPAIR_COST_PER_HP
    token = await game.tokens.issue(uid, message.chat.id, "repair")
    await message.answer(
        f"🛠 Повреждения: {missing} HP (❤️ {p.ship.hp}/{p.ship.max_hp}). "
        f"Полный ремонт: <b>{cost}</b> кр. ({REPAIR_COST_PER_HP} кр./HP), баланс {p.balance}.\n"
        "Частичный ремонт: <code>/repair 20</code>",
        reply_markup=single_action_kb(f"🛠 Полный ремонт за {cost} кр.", token, "full"),
    )


# ----------------------------------------------------------------- добыча
def mine_text(r: MineResult) -> str:
    return (
        f"⛏ Добыто: <b>{r.quantity} × {item_title(r.item_id)}</b>\n"
        f"🔋 Осталось {r.energy_left} | 📦 {r.cargo_used}/{r.capacity}{progress_lines(r.progress)}"
    )


async def mine_again_kb(game: Game, user_id: int, chat_id: int | None):
    token = await game.tokens.issue(user_id, chat_id, "mine")
    return single_action_kb(f"⛏ Добывать ещё ({MINE_ENERGY} 🔋)", token)


@router.message(Command("mine"))
async def cmd_mine(message: Message, game: Game) -> None:
    result = await game.mining.mine(message.from_user.id)
    await message.answer(
        mine_text(result), reply_markup=await mine_again_kb(game, message.from_user.id, message.chat.id)
    )


# ----------------------------------------------------------------- крафт
@router.message(Command("recipes"))
async def cmd_recipes(message: Message) -> None:
    await message.answer(recipes_text())


def craft_text(r: CraftResult) -> str:
    used = ", ".join(f"{q} {item_title(i)}" for i, q in r.consumed.items())
    return (
        f"🛠 Произведено: <b>{r.quantity} × {item_title(r.item_id)}</b>\n"
        f"Израсходовано: {used}; работа {r.fee} кр. 💰 Баланс: {r.balance}{progress_lines(r.progress)}"
    )


@router.message(Command("craft"))
async def cmd_craft(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if not args or len(args) > 2:
        raise ValidationError(
            "✍️ Формат: <code>/craft &lt;товар&gt; [количество]</code>, например "
            "<code>/craft fuel_cell 3</code>. Рецепты: /recipes"
        )
    item_id = validate_recipe(args[0])
    qty = parse_int(args[1], "количество", 1, MAX_CRAFT_QTY) if len(args) == 2 else 1
    ingredients = ", ".join(f"{q * qty} {item_title(i)}" for i, q in RECIPES[item_id].items())
    token = await game.tokens.issue(message.from_user.id, message.chat.id, "craft", {"item": item_id, "qty": qty})
    await message.answer(
        f"🛠 Произвести <b>{qty} × {item_title(item_id)}</b>?\nИнгредиенты: {esc(ingredients)}; работа {10 * qty} кр.",
        reply_markup=single_action_kb("✅ Подтвердить производство", token, "ok"),
    )
