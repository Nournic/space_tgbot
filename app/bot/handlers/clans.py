"""Кланы: /clan и подкоманды."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import clan_text, esc
from app.bot.keyboards import NavCB, disband_kb, pager_kb
from app.bot.utils import cb_answer, display_name, parse_int, reply_target, safe_edit
from app.constants import CLAN_CREATE_COST, CLAN_MAX_MEMBERS, MAX_DONATE
from app.errors import ValidationError
from app.services import Game

router = Router(name="clans")

CLAN_HELP = f"""🏰 <b>Кланы</b>
<code>/clan create Название</code> — создать ({CLAN_CREATE_COST} кр.)
<code>/clan list</code> — открытые кланы
<code>/clan join ID</code> — вступить (максимум {CLAN_MAX_MEMBERS} участников)
<code>/clan leave</code> — выйти
<code>/clan info [ID]</code> — информация
<code>/clan donate 500</code> — взнос в казну
<code>/clan transfer</code> — ответом на сообщение участника: передать лидерство
<code>/clan disband</code> — распустить (только лидер; казна сгорает)"""


async def render_clan_list(game: Game, page: int) -> tuple[str, object]:
    clans, page, pages = await game.clans.list_open(page)
    lines = [f"🏰 <b>Открытые кланы</b> (стр. {page + 1}/{pages})", ""]
    if not clans:
        lines.append("Кланов пока нет. Создайте первый: <code>/clan create Название</code>")
    for c in clans:
        lines.append(f"ID <b>{c.id}</b> · {esc(c.name)} · 👥 {c.member_count}/{CLAN_MAX_MEMBERS} · 🏦 {c.treasury}")
    lines.append("\nВступить: <code>/clan join ID</code>")
    return "\n".join(lines), pager_kb("cl", 0, page, pages)


@router.message(Command("clan"))
async def cmd_clan(message: Message, command: CommandObject, game: Game) -> None:
    uid = message.from_user.id
    raw = (command.args or "").strip()
    sub, _, rest = raw.partition(" ")
    sub, rest = sub.lower(), rest.strip()

    if not sub:
        clan_id = await game.clans.my_clan_id(uid)
        status = clan_text(await game.clans.info(uid, clan_id)) if clan_id else "Вы не состоите в клане."
        await message.answer(f"{status}\n\n{CLAN_HELP}")
    elif sub == "create":
        view = await game.clans.create(uid, rest)
        await message.answer(f"🎉 Клан создан за {CLAN_CREATE_COST} кр.!\n\n{clan_text(view)}")
    elif sub == "list":
        page = parse_int(rest, "страница", 1, 10_000) - 1 if rest else 0
        text, kb = await render_clan_list(game, page)
        await message.answer(text, reply_markup=kb)
    elif sub == "join":
        view = await game.clans.join(uid, parse_int(rest, "ID клана", 1, 10**12))
        await message.answer(f"✅ Вы вступили в клан!\n\n{clan_text(view)}")
    elif sub == "leave":
        name = await game.clans.leave(uid)
        await message.answer(f"👋 Вы покинули клан «{esc(name)}».")
    elif sub == "info":
        clan_id = parse_int(rest, "ID клана", 1, 10**12) if rest else None
        await message.answer(clan_text(await game.clans.info(uid, clan_id)))
    elif sub == "donate":
        if not rest:
            raise ValidationError("✍️ Формат: <code>/clan donate 500</code>")
        view, balance = await game.clans.donate(uid, parse_int(rest, "сумма", 1, MAX_DONATE))
        await message.answer(f"🏦 Взнос принят. Казна «{esc(view.name)}»: {view.treasury} кр. Ваш баланс: {balance}")
    elif sub == "transfer":
        target = reply_target(message)
        await game.accounts.touch_name(target.id, display_name(target))
        view = await game.clans.transfer(uid, target.id)
        await message.answer(f"👑 Лидерство передано: {esc(view.leader_name)}\n\n{clan_text(view)}")
    elif sub == "disband":
        view = await game.clans.leader_clan(uid)
        token = await game.tokens.issue(uid, message.chat.id, "clan_disband", {"clan_id": view.id})
        await message.answer(
            f"⚠️ Распустить клан «{esc(view.name)}»?\n"
            f"Казна <b>{view.treasury}</b> кр. <b>сгорит без возврата</b> участникам. Действие необратимо.",
            reply_markup=disband_kb(token),
        )
    else:
        await message.answer(CLAN_HELP)


@router.callback_query(NavCB.filter(F.view == "cl"))
async def cb_clan_list(callback: CallbackQuery, callback_data: NavCB, game: Game) -> None:
    text, kb = await render_clan_list(game, int(callback_data.arg) if callback_data.arg.isdigit() else 0)
    await safe_edit(callback.message, text, kb)
    await cb_answer(callback)
