"""Прогресс: /quests, /claim, /achievements, /top."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import achievements_text, progress_lines, quests_text, top_text
from app.bot.keyboards import NavCB, quests_kb, top_kb
from app.bot.utils import cb_answer, safe_edit, split_args
from app.clock import utc_date
from app.constants import QUESTS
from app.errors import ValidationError
from app.models import ClaimResult
from app.services import Game
from app.services.rankings import CATEGORIES

router = Router(name="progression")


async def render_quests(game: Game, user_id: int, chat_id: int | None, prefix: str = ""):
    day, quests = await game.quests.today(user_id)
    kb = None
    if any(q.done and not q.claimed for q in quests):
        token = await game.tokens.issue(user_id, chat_id, "quests", {"date": utc_date(game.ctx.clock.now())})
        kb = quests_kb(token, quests)
    return prefix + quests_text(day, quests), kb


def claim_text(r: ClaimResult) -> str:
    return (f"🎁 Награда за «{QUESTS[r.quest_id].title}»: +{r.credits} кр., +{r.xp} XP. "
            f"💰 Баланс: {r.balance}{progress_lines(r.progress)}")


@router.message(Command("quests"))
async def cmd_quests(message: Message, game: Game) -> None:
    text, kb = await render_quests(game, message.from_user.id, message.chat.id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("claim"))
async def cmd_claim(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    if len(args) != 1:
        raise ValidationError("✍️ Формат: <code>/claim daily_sell</code>. Список: /quests")
    result = await game.quests.claim(message.from_user.id, args[0])
    await message.answer(claim_text(result))


@router.message(Command("achievements"))
async def cmd_achievements(message: Message, game: Game) -> None:
    await message.answer(achievements_text(await game.quests.achievements(message.from_user.id)))


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, game: Game) -> None:
    args = split_args(command.args)
    category = args[0].lower() if args and args[0].lower() in CATEGORIES else "balance"
    ranking = await game.rankings.top(category, message.from_user.id)
    await message.answer(top_text(ranking), reply_markup=top_kb(category))


@router.callback_query(NavCB.filter(F.view == "tp"))
async def cb_top(callback: CallbackQuery, callback_data: NavCB, game: Game) -> None:
    category = callback_data.arg if callback_data.arg in CATEGORIES else "balance"
    ranking = await game.rankings.top(category, callback.from_user.id)
    await safe_edit(callback.message, top_text(ranking), top_kb(category))
    await cb_answer(callback)
