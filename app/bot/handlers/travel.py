"""Карта и перелёты: /map, /travel."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.formatting import planet_title, progress_lines
from app.bot.keyboards import travel_kb
from app.bot.utils import parse_planet, split_args
from app.constants import PLANET_ORDER, PLANETS, ROUTES
from app.models import TravelResult
from app.services import Game
from app.services.base import format_duration

router = Router(name="travel")


def map_overview(here: str) -> str:
    lines = ["🗺 <b>Карта сектора</b>"]
    for pid in PLANET_ORDER:
        marker = "📍" if pid == here else "▫️"
        links = ", ".join(f"{PLANETS[d].name} ({c})" for d, c in ROUTES[pid].items())
        lines.append(f"{marker} {planet_title(pid)} — {PLANETS[pid].description}\n      ↔ {links}")
    return "\n".join(lines)


async def render_travel(game: Game, user_id: int, chat_id: int | None, prefix: str = ""):
    here, costs = await game.travel.destinations(user_id)
    p = await game.accounts.profile(user_id)
    now = game.ctx.clock.now()
    cd = p.ship.travel_cooldown_until - now
    cd_line = f"\n⏱ Перелёт доступен через {format_duration(cd)}" if cd > 0 else ""
    token = await game.tokens.issue(user_id, chat_id, "travel", {"from": here})
    text = (f"{prefix}{map_overview(here)}\n\n"
            f"Вы на: <b>{planet_title(here)}</b> | 🔋 {p.ship.energy}/100 | ❤️ {p.ship.hp}/{p.ship.max_hp}{cd_line}\n"
            "Куда летим? (стоимость в энергии с учётом двигателя)")
    return text, travel_kb(token, costs)


def travel_result_text(r: TravelResult) -> str:
    return (f"🚀 Перелёт {planet_title(r.from_planet)} → <b>{planet_title(r.to_planet)}</b> завершён!\n"
            f"🔋 −{r.energy_cost}, осталось {r.energy_left}. Следующий перелёт через 60 сек."
            f"{progress_lines(r.progress)}\n\nОткройте /market, чтобы торговать.")


@router.message(Command("map"))
async def cmd_map(message: Message, game: Game) -> None:
    text, kb = await render_travel(game, message.from_user.id, message.chat.id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("travel"))
async def cmd_travel(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if not args:
        text, kb = await render_travel(game, message.from_user.id, message.chat.id)
        await message.answer(text, reply_markup=kb)
        return
    result = await game.travel.travel(message.from_user.id, parse_planet(" ".join(args)))
    await message.answer(travel_result_text(result))
