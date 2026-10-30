"""PvE: /hunt."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.formatting import enemy_title, progress_lines
from app.bot.keyboards import single_action_kb
from app.constants import HUNT_ENERGY
from app.models import HuntResult
from app.services import Game

router = Router(name="pve")


def hunt_text(r: HuntResult) -> str:
    head = f"☠️ Встреча: <b>{enemy_title(r.enemy_id)}</b>\n⚔️ Ваша сила {r.player_power} против {r.enemy_power}\n"
    if r.won:
        outcome = f"🏆 <b>Победа!</b> Награда: {r.reward} кр."
    else:
        outcome = "💥 <b>Поражение.</b> Пират ушёл, груз не пострадал."
    hp = f"\n🩹 Урон −{r.damage} HP, прочность {r.hp_left}/{r.max_hp} | 🔋 {r.energy_left}"
    warn = "\n⚠️ Корабль разрушен! /repair" if r.hp_left == 0 else ""
    return head + outcome + hp + warn + progress_lines(r.progress)


async def hunt_again_kb(game: Game, user_id: int, chat_id: int | None):
    token = await game.tokens.issue(user_id, chat_id, "hunt")
    return single_action_kb(f"☠️ Охотиться ещё ({HUNT_ENERGY} 🔋)", token)


@router.message(Command("hunt"))
async def cmd_hunt(message: Message, game: Game) -> None:
    result = await game.combat.hunt(message.from_user.id)
    kb = await hunt_again_kb(game, message.from_user.id, message.chat.id) if result.hp_left > 0 else None
    await message.answer(hunt_text(result), reply_markup=kb)
