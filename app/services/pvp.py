"""Добровольные PvP-дуэли со ставками в escrow.

Escrow: при создании вызова ставка инициатора списывается с баланса и
хранится в строке вызова (status='pending'). Любой переход из 'pending'
выполняется условным UPDATE ... WHERE status='pending', поэтому выплата или
возврат происходят строго один раз даже при конкурентных нажатиях.

Формула дуэли: сила = атака по PvE-формуле + 2 × уровень брони.
Большая сила побеждает, равная — ничья.
Урон проигравшему: max(1, random(20..35) − 2 × броня);
победителю (и обоим при ничьей): random(0..10), снижаемый бронёй (0 остаётся 0).
"""

from __future__ import annotations

from app.constants import (
    CHALLENGE_TTL,
    MAX_STAKE,
    PVP_DEFENSE_PER_ARMOR,
    PVP_ENERGY,
    PVP_LOSER_DAMAGE,
    PVP_WINNER_DAMAGE,
    PVP_XP_PAIR_COOLDOWN,
    XP_PVP_DRAW,
    XP_PVP_LOSS,
    XP_PVP_WIN,
)
from app.db import repositories as repo
from app.db.connection import Conn
from app.errors import GameError, NotYourButton, StaleAction, ValidationError
from app.models import ChallengeView, DuelResult, ExpiredNotice, Progress
from app.services import progression
from app.services.base import ServiceContext, load_ship, save_ship, spend_energy
from app.services.combat import attack_power, mitigate

_SELECT = (
    "SELECT p.*, cu.display_name AS challenger_name, tu.display_name AS target_name "
    "FROM pvp_challenges p JOIN users cu ON cu.user_id = p.challenger_id "
    "JOIN users tu ON tu.user_id = p.target_id"
)


def _view(row) -> ChallengeView:
    return ChallengeView(
        id=int(row["id"]),
        challenger_id=int(row["challenger_id"]),
        challenger_name=row["challenger_name"],
        target_id=int(row["target_id"]),
        target_name=row["target_name"],
        stake=int(row["stake"]),
        status=row["status"],
        created_at=int(row["created_at"]),
        expires_at=int(row["expires_at"]),
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        winner_id=None if row["winner_id"] is None else int(row["winner_id"]),
    )


async def _get(conn: Conn, challenge_id: int):
    cur = await conn.execute(f"{_SELECT} WHERE p.id = ?", (challenge_id,))
    row = await cur.fetchone()
    if row is None:
        raise StaleAction()
    return row


async def _close_with_refund(conn: Conn, row, status: str, now: int) -> bool:
    """Переводит pending-вызов в финальный статус и возвращает ставку ровно один раз."""
    cur = await conn.execute(
        "UPDATE pvp_challenges SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
        (status, now, int(row["id"])),
    )
    if cur.rowcount != 1:
        return False
    stake = int(row["stake"])
    if stake > 0:
        await repo.change_balance(conn, int(row["challenger_id"]), stake, now)
        await repo.add_ledger(
            conn,
            int(row["challenger_id"]),
            "pvp_refund",
            stake,
            now,
            counterparty_id=int(row["target_id"]),
            ref_type="pvp",
            ref_id=int(row["id"]),
            details=status,
        )
    return True


class PvpService:
    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    async def create(self, challenger_id: int, target_id: int, stake: int, chat_id: int | None) -> ChallengeView:
        if isinstance(stake, bool) or not isinstance(stake, int) or stake < 0 or stake > MAX_STAKE:
            raise ValidationError(f"💰 Ставка — целое число от 0 до {MAX_STAKE}.")
        if challenger_id == target_id:
            raise ValidationError("🤨 Нельзя вызвать на дуэль самого себя.")
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            me = await repo.require_user(conn, challenger_id)
            other = await repo.require_other_user(conn, target_id)
            if me["planet_id"] != other["planet_id"]:
                raise GameError("🪐 Соперник находится на другой планете.")
            my_ship = await load_ship(conn, challenger_id, now)
            their_ship = await load_ship(conn, target_id, now)
            if my_ship.hp <= 0:
                raise GameError("🛠 Ваш корабль разрушен. Сначала /repair.")
            if their_ship.hp <= 0:
                raise GameError("🛠 Корабль соперника разрушен.")
            if my_ship.energy < PVP_ENERGY:
                raise GameError(f"🔋 Для дуэли нужно {PVP_ENERGY} энергии.")
            cur = await conn.execute(
                "SELECT 1 FROM pvp_challenges WHERE challenger_id = ? AND target_id = ? "
                "AND status = 'pending' AND expires_at > ?",
                (challenger_id, target_id, now),
            )
            if await cur.fetchone():
                raise GameError("⏳ У вас уже есть активный вызов этому игроку.")
            cur = await conn.execute(
                "INSERT INTO pvp_challenges (challenger_id, target_id, stake, status, chat_id, created_at, expires_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (challenger_id, target_id, stake, chat_id, now, now + CHALLENGE_TTL),
            )
            challenge_id = int(cur.lastrowid)
            if stake > 0:
                await repo.change_balance(conn, challenger_id, -stake, now)
                await repo.add_ledger(
                    conn,
                    challenger_id,
                    "pvp_escrow",
                    -stake,
                    now,
                    counterparty_id=target_id,
                    ref_type="pvp",
                    ref_id=challenge_id,
                )
            view = _view(await _get(conn, challenge_id))
        return view

    async def set_message(self, challenge_id: int, message_id: int) -> None:
        async with self.ctx.db.transaction() as conn:
            await conn.execute("UPDATE pvp_challenges SET message_id = ? WHERE id = ?", (message_id, challenge_id))

    async def get(self, challenge_id: int) -> ChallengeView:
        async with self.ctx.db.read() as conn:
            return _view(await _get(conn, challenge_id))

    async def decline(self, challenge_id: int, user_id: int) -> ChallengeView:
        return await self._close(challenge_id, user_id, "declined")

    async def cancel(self, challenge_id: int, user_id: int) -> ChallengeView:
        return await self._close(challenge_id, user_id, "cancelled")

    async def _close(self, challenge_id: int, user_id: int, status: str) -> ChallengeView:
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            row = await _get(conn, challenge_id)
            allowed = int(row["target_id"]) if status == "declined" else int(row["challenger_id"])
            if user_id != allowed:
                raise NotYourButton()
            if row["status"] != "pending":
                raise StaleAction()
            final = "expired" if int(row["expires_at"]) <= now else status
            if not await _close_with_refund(conn, row, final, now):
                raise StaleAction()
            view = _view(await _get(conn, challenge_id))
        return view

    async def accept(self, challenge_id: int, user_id: int) -> DuelResult:
        rng = self.ctx.rng
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            row = await _get(conn, challenge_id)
            if user_id != int(row["target_id"]):
                raise NotYourButton()
            if row["status"] != "pending":
                raise StaleAction()
            if int(row["expires_at"]) <= now:
                await _close_with_refund(conn, row, "expired", now)
                return DuelResult(challenge=_view(await _get(conn, challenge_id)), status="expired")

            a_id, b_id, stake = int(row["challenger_id"]), int(row["target_id"]), int(row["stake"])
            a_user, b_user = await repo.require_user(conn, a_id), await repo.require_user(conn, b_id)
            if a_user["planet_id"] != b_user["planet_id"]:
                raise GameError("🪐 Дуэлянты должны находиться на одной планете.")
            a_ship, b_ship = await load_ship(conn, a_id, now), await load_ship(conn, b_id, now)
            if a_ship.hp <= 0 or b_ship.hp <= 0:
                raise GameError("🛠 Один из кораблей разрушен — дуэль невозможна.")
            if a_ship.energy < PVP_ENERGY:
                raise GameError("🔋 У инициатора недостаточно энергии для дуэли.")
            if b_ship.energy < PVP_ENERGY:
                raise GameError(f"🔋 Для дуэли нужно {PVP_ENERGY} энергии.")
            cur = await conn.execute(
                "UPDATE pvp_challenges SET status = 'resolved', resolved_at = ? WHERE id = ? AND status = 'pending'",
                (now, challenge_id),
            )
            if cur.rowcount != 1:
                raise StaleAction()
            if stake > 0:
                await repo.change_balance(conn, b_id, -stake, now)
                await repo.add_ledger(
                    conn, b_id, "pvp_escrow", -stake, now, counterparty_id=a_id, ref_type="pvp", ref_id=challenge_id
                )
            spend_energy(a_ship, PVP_ENERGY, now)
            spend_energy(b_ship, PVP_ENERGY, now)

            a_power = attack_power(a_ship, rng) + PVP_DEFENSE_PER_ARMOR * a_ship.armor_level
            b_power = attack_power(b_ship, rng) + PVP_DEFENSE_PER_ARMOR * b_ship.armor_level
            if a_power == b_power:
                winner = None
                a_dmg = mitigate(rng.randint(*PVP_WINNER_DAMAGE), a_ship.armor_level)
                b_dmg = mitigate(rng.randint(*PVP_WINNER_DAMAGE), b_ship.armor_level)
            else:
                winner = a_id if a_power > b_power else b_id
                loser_ship, winner_ship = (b_ship, a_ship) if winner == a_id else (a_ship, b_ship)
                loser_dmg = mitigate(rng.randint(*PVP_LOSER_DAMAGE), loser_ship.armor_level)
                winner_dmg = mitigate(rng.randint(*PVP_WINNER_DAMAGE), winner_ship.armor_level)
                a_dmg, b_dmg = (winner_dmg, loser_dmg) if winner == a_id else (loser_dmg, winner_dmg)
            a_ship.hp = max(0, a_ship.hp - a_dmg)
            b_ship.hp = max(0, b_ship.hp - b_dmg)
            await save_ship(conn, a_ship, now)
            await save_ship(conn, b_ship, now)

            # Выплаты из escrow: 2 × ставка победителю, при ничьей — возврат каждому.
            if stake > 0:
                if winner is None:
                    for uid, other in ((a_id, b_id), (b_id, a_id)):
                        await repo.change_balance(conn, uid, stake, now)
                        await repo.add_ledger(
                            conn,
                            uid,
                            "pvp_refund",
                            stake,
                            now,
                            counterparty_id=other,
                            ref_type="pvp",
                            ref_id=challenge_id,
                            details="draw",
                        )
                else:
                    loser = b_id if winner == a_id else a_id
                    await repo.change_balance(conn, winner, 2 * stake, now)
                    await repo.inc_stats(conn, winner, credits_earned=stake)
                    await repo.add_ledger(
                        conn,
                        winner,
                        "pvp_win",
                        2 * stake,
                        now,
                        counterparty_id=loser,
                        ref_type="pvp",
                        ref_id=challenge_id,
                    )

            # Ограничение фарма XP: одна пара — не чаще раза в час.
            pair = (min(a_id, b_id), max(a_id, b_id))
            cur = await conn.execute("SELECT last_xp_at FROM pvp_xp_cooldowns WHERE user_a = ? AND user_b = ?", pair)
            last = await cur.fetchone()
            xp_allowed = last is None or now - int(last[0]) >= PVP_XP_PAIR_COOLDOWN
            if winner is None:
                a_xp = b_xp = XP_PVP_DRAW
            else:
                a_xp = XP_PVP_WIN if winner == a_id else XP_PVP_LOSS
                b_xp = XP_PVP_WIN if winner == b_id else XP_PVP_LOSS
            if not xp_allowed:
                a_xp = b_xp = 0
            else:
                await conn.execute(
                    "INSERT INTO pvp_xp_cooldowns (user_a, user_b, last_xp_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_a, user_b) DO UPDATE SET last_xp_at = excluded.last_xp_at",
                    (*pair, now),
                )
            a_prog, b_prog = Progress(), Progress()
            for uid, xp, prog in ((a_id, a_xp, a_prog), (b_id, b_xp, b_prog)):
                if winner is None:
                    await repo.inc_stats(conn, uid, pvp_draws=1)
                elif winner == uid:
                    await repo.inc_stats(conn, uid, pvp_wins=1)
                else:
                    await repo.inc_stats(conn, uid, pvp_losses=1)
                await progression.add_xp(conn, uid, xp, now, prog)
                await progression.check_achievements(conn, uid, now, prog)
            await conn.execute(
                "UPDATE pvp_challenges SET winner_id = ?, challenger_power = ?, target_power = ? WHERE id = ?",
                (winner, a_power, b_power, challenge_id),
            )
            view = _view(await _get(conn, challenge_id))
        return DuelResult(
            challenge=view,
            status="resolved",
            challenger_power=a_power,
            target_power=b_power,
            winner_id=winner,
            challenger_damage=a_dmg,
            target_damage=b_dmg,
            challenger_hp=a_ship.hp,
            target_hp=b_ship.hp,
            challenger_xp=a_xp,
            target_xp=b_xp,
            xp_capped=not xp_allowed,
            challenger_progress=a_prog,
            target_progress=b_prog,
        )

    async def list_for(self, user_id: int, limit: int = 10) -> list[ChallengeView]:
        async with self.ctx.db.read() as conn:
            await repo.require_user(conn, user_id)
            cur = await conn.execute(
                f"{_SELECT} WHERE (p.challenger_id = ? OR p.target_id = ?) "
                "ORDER BY CASE WHEN p.status = 'pending' THEN 0 ELSE 1 END, p.id DESC LIMIT ?",
                (user_id, user_id, limit),
            )
            return [_view(r) for r in await cur.fetchall()]

    async def expire_due(self) -> list[ExpiredNotice]:
        """Идемпотентно закрывает просроченные вызовы с возвратом ставок."""
        notices: list[ExpiredNotice] = []
        async with self.ctx.db.transaction() as conn:
            now = self.ctx.clock.now()
            cur = await conn.execute(f"{_SELECT} WHERE p.status = 'pending' AND p.expires_at <= ?", (now,))
            for row in await cur.fetchall():
                if await _close_with_refund(conn, row, "expired", now):
                    notices.append(
                        ExpiredNotice(
                            "challenge",
                            int(row["id"]),
                            row["chat_id"],
                            row["message_id"],
                            f"⌛ Вызов #{row['id']} истёк. Ставка возвращена инициатору.",
                        )
                    )
        return notices
