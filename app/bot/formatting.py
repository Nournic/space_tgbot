"""HTML-форматирование ответов. Все пользовательские строки экранируются."""

from __future__ import annotations

from html import escape

from app.clock import format_utc
from app.constants import (
    ACHIEVEMENTS,
    CLAN_MAX_MEMBERS,
    CRAFT_FEE_PER_UNIT,
    ENEMIES,
    ITEM_ORDER,
    ITEMS,
    MAX_ENERGY,
    MODULE_MAX_LEVEL,
    MODULE_ORDER,
    MODULES,
    PLANETS,
    QUESTS,
    RECIPES,
    SHIP_CLASSES,
    STAT_FIELDS,
    XP_CRAFT,
    XP_PER_LEVEL,
)
from app.models import (
    AchievementStatus,
    ChallengeView,
    ClanView,
    DuelResult,
    HistoryPage,
    OfferView,
    Profile,
    Progress,
    QuestView,
    Ranking,
    ShipState,
)
from app.services.base import format_duration


def esc(text: object) -> str:
    return escape(str(text), quote=False)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={int(user_id)}">{esc(name)}</a>'


def item_title(item_id: str) -> str:
    return ITEMS[item_id].title


def planet_title(planet_id: str) -> str:
    return PLANETS[planet_id].title


def energy_line(ship: ShipState, now: int) -> str:
    line = f"🔋 Энергия: <b>{ship.energy}/{MAX_ENERGY}</b>"
    wait = ship.seconds_to_next_energy(now)
    if wait is not None:
        line += f" (+1 через {format_duration(wait)})"
    return line


def status_block(p: Profile, now: int) -> str:
    return (
        f"💰 Баланс: <b>{p.balance}</b> кр. | 📍 {planet_title(p.planet_id)}\n"
        f"📦 Трюм: <b>{p.cargo_used}/{p.ship.capacity}</b> | ❤️ HP: <b>{p.ship.hp}/{p.ship.max_hp}</b>\n"
        f"{energy_line(p.ship, now)}"
    )


def progress_lines(progress: Progress | None) -> str:
    if progress is None:
        return ""
    parts = []
    if progress.xp_gained:
        parts.append(f"⭐ +{progress.xp_gained} XP")
    if progress.leveled_up:
        parts.append(f"🎉 Новый уровень: <b>{progress.new_level}</b>!")
    for qid in progress.quests_completed:
        parts.append(f"📋 Задание выполнено: {esc(QUESTS[qid].title)} — заберите награду в /quests")
    for aid in progress.achievements:
        parts.append(f"🏆 Достижение: <b>{esc(ACHIEVEMENTS[aid].title)}</b>")
    return ("\n" + "\n".join(parts)) if parts else ""


def profile_text(p: Profile, now: int) -> str:
    level_xp = p.xp % XP_PER_LEVEL
    clan = esc(p.clan_name) if p.clan_name else "—"
    return (
        f"👤 <b>{esc(p.display_name)}</b>\n"
        f"⭐ Уровень <b>{p.level}</b> (XP {p.xp}, до следующего {XP_PER_LEVEL - level_xp})\n"
        f"🏰 Клан: {clan}\n"
        f"🚀 Корабль: <b>{esc(p.ship.class_name)}</b>\n"
        f"{status_block(p, now)}\n\n"
        f"{stats_text(p.stats)}"
    )


STAT_LABELS = {
    "trades": "🛍 Рыночных сделок",
    "units_bought": "📥 Куплено единиц",
    "units_sold": "📤 Продано единиц",
    "travels": "🚀 Перелётов",
    "units_mined": "⛏ Добыто единиц",
    "crafts": "🛠 Производств",
    "pve_wins": "☠️ Побед над пиратами",
    "pve_losses": "💥 Поражений от пиратов",
    "pvp_wins": "⚔️ Побед в дуэлях",
    "pvp_losses": "🩸 Поражений в дуэлях",
    "pvp_draws": "🤝 Ничьих в дуэлях",
    "quests_completed": "📋 Наград за задания",
    "credits_earned": "💹 Заработано кредитов",
}


def stats_text(stats: dict[str, int]) -> str:
    return "📊 <b>Статистика</b>\n" + "\n".join(f"{STAT_LABELS[k]}: {stats[k]}" for k in STAT_FIELDS)


def inventory_text(p: Profile) -> str:
    lines = [f"📦 <b>Трюм</b>: {p.cargo_used}/{p.ship.capacity}"]
    if not p.inventory:
        lines.append("Пусто. Купите товары в /market или добудьте в /mine.")
    for item_id in ITEM_ORDER:
        qty = p.inventory.get(item_id, 0)
        if qty:
            reserved = p.reserved.get(item_id, 0)
            extra = f" (🔒 {reserved} в P2P-резерве)" if reserved else ""
            lines.append(f"{item_title(item_id)}: <b>{qty}</b> × {ITEMS[item_id].weight} ед.{extra}")
    return "\n".join(lines)


def ship_text(p: Profile, now: int) -> str:
    s = p.ship
    lines = [
        f"🚀 <b>{esc(s.class_name)}</b>",
        f"❤️ Прочность: {s.hp}/{s.max_hp}",
        f"📦 Трюм: {p.cargo_used}/{s.capacity}",
        energy_line(s, now),
        "",
        "🔧 <b>Модули</b>:",
    ]
    for m in MODULE_ORDER:
        lines.append(f"{MODULES[m]}: {s.module_level(m)}/{MODULE_MAX_LEVEL}")
    cds = []
    for label, until in (
        ("перелёт", s.travel_cooldown_until),
        ("добыча", s.mine_cooldown_until),
        ("охота", s.hunt_cooldown_until),
    ):
        if until > now:
            cds.append(f"{label} — {format_duration(until - now)}")
    if cds:
        lines.append("\n⏱ Кулдауны: " + ", ".join(cds))
    return "\n".join(lines)


def shipyard_text(p: Profile) -> str:
    lines = ["🏗 <b>Верфь</b>", f"Ваш корабль: {esc(p.ship.class_name)}, баланс {p.balance} кр., уровень {p.level}", ""]
    for sc in SHIP_CLASSES.values():
        price = "стартовый" if sc.price is None else f"{sc.price} кр."
        mark = " ✅" if sc.id == p.ship.ship_class else ""
        lines.append(
            f"<b>{sc.name}</b> (<code>{sc.id}</code>){mark}: {price}, трюм {sc.cargo}, HP {sc.hp}, "
            f"бонус атаки +{sc.combat_bonus}, ур. {sc.min_level}+"
        )
    lines.append("\nПокупка заменяет корпус: модули, груз и энергия сохраняются, прочность — полная.")
    return "\n".join(lines)


def market_text(planet_id: str, prices: dict[str, tuple[int, int]], p: Profile, now: int, event_title: str) -> str:
    lines = [
        f"🏪 <b>Рынок: {planet_title(planet_id)}</b>",
        f"🌐 Событие дня: {esc(event_title)}",
        "",
        "Товар — покупка / продажа (вес):",
    ]
    for item_id in ITEM_ORDER:
        b, s = prices[item_id]
        have = p.inventory.get(item_id, 0)
        own = f" | у вас {have}" if have else ""
        lines.append(f"{item_title(item_id)} — <b>{b}</b> / {s} ({ITEMS[item_id].weight}){own}")
    lines.append("")
    lines.append(status_block(p, now))
    lines.append("\nВыберите товар кнопкой или: <code>/buy water 5</code>, <code>/sell iron 2</code>")
    return "\n".join(lines)


def prices_text(table: dict[str, dict[str, tuple[int, int]]], items: list[str], page: int, pages: int, day: str) -> str:
    lines = [f"📈 <b>Цены всех планет</b> ({day} UTC), стр. {page + 1}/{pages}", "покупка / продажа"]
    for item_id in items:
        lines.append(f"\n<b>{item_title(item_id)}</b>")
        best_buy = min(table[p][item_id][0] for p in table)
        best_sell = max(table[p][item_id][1] for p in table)
        for planet_id, prices in table.items():
            b, s = prices[item_id]
            marks = ("🟢" if b == best_buy else "") + ("💎" if s == best_sell else "")
            lines.append(f"  {planet_title(planet_id)}: {b} / {s} {marks}")
    lines.append("\n🟢 дешевле всего купить, 💎 дороже всего продать")
    return "\n".join(lines)


def recipes_text() -> str:
    lines = [f"🛠 <b>Рецепты</b> (работа — {CRAFT_FEE_PER_UNIT} кр. за единицу, +{XP_CRAFT} XP за операцию)", ""]
    for out, ingredients in RECIPES.items():
        ing = " + ".join(f"{q} {item_title(i)}" for i, q in ingredients.items())
        lines.append(f"1 {item_title(out)} (<code>{out}</code>) ← {ing}")
    lines.append("\nПример: <code>/craft fuel_cell 3</code>")
    return "\n".join(lines)


def quests_text(day: str, quests: list[QuestView]) -> str:
    lines = [f"📋 <b>Ежедневные задания</b> ({day} UTC)", ""]
    for q in quests:
        quest = QUESTS[q.quest_id]
        state = "✅ получено" if q.claimed else ("🎁 готово к получению" if q.done else f"{q.progress}/{q.target}")
        lines.append(
            f"<b>{esc(quest.title)}</b> (<code>{q.quest_id}</code>)\n"
            f"  Прогресс: {state} | награда {quest.reward_credits} кр., {quest.reward_xp} XP"
        )
    lines.append("\nЗадания обновляются в 00:00 UTC. Получить: <code>/claim daily_sell</code>")
    return "\n".join(lines)


def achievements_text(items: list[AchievementStatus]) -> str:
    earned = sum(1 for a in items if a.earned)
    lines = [f"🏆 <b>Достижения</b> {earned}/{len(items)}", ""]
    for a in items:
        ach = ACHIEVEMENTS[a.achievement_id]
        if a.earned:
            lines.append(f"✅ <b>{esc(ach.title)}</b> — {esc(ach.description)} ({format_utc(a.earned_at or 0)})")
        else:
            lines.append(f"▫️ {esc(ach.title)} — {esc(ach.description)} [{a.current}/{a.target}]")
    return "\n".join(lines)


TOP_TITLES = {
    "balance": "💰 Баланс",
    "xp": "⭐ Уровень / XP",
    "pve": "☠️ Победы над пиратами",
    "pvp": "⚔️ PvP-победы",
    "clans": "🏰 Кланы по казне",
}


def top_text(r: Ranking) -> str:
    lines = [f"🏅 <b>Рейтинг: {TOP_TITLES[r.category]}</b>", ""]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if not r.rows:
        lines.append("Пока пусто.")
    for row in r.rows:
        lines.append(f"{medals.get(row.place, f'{row.place}.')} {esc(row.name)} — <b>{row.value}</b> {esc(row.extra)}")
    if r.me is not None:
        lines.append(f"\n…\n{r.me.place}. {esc(r.me.name)} — <b>{r.me.value}</b> {esc(r.me.extra)} (вы)")
    return "\n".join(lines)


KIND_LABELS = {
    "register": "🎁 Регистрация",
    "market_buy": "🛒 Покупка",
    "market_sell": "💵 Продажа",
    "mine": "⛏ Добыча",
    "craft": "🛠 Производство",
    "pve_win": "☠️ Победа над пиратом",
    "pve_loss": "💥 Поражение от пирата",
    "pvp_escrow": "🔒 Ставка в дуэли",
    "pvp_refund": "↩️ Возврат ставки",
    "pvp_win": "⚔️ Выигрыш дуэли",
    "p2p_buy": "🤝 P2P-покупка",
    "p2p_sell": "🤝 P2P-продажа",
    "ship_buy": "🚀 Покупка корабля",
    "upgrade": "🔧 Улучшение",
    "repair": "🛠 Ремонт",
    "quest_reward": "📋 Награда за задание",
    "clan_create": "🏰 Создание клана",
    "clan_donate": "🏦 Взнос в казну",
    "clan_disband": "💨 Роспуск клана",
}


def history_text(h: HistoryPage) -> str:
    lines = [f"🧾 <b>История операций</b> (стр. {h.page + 1}/{h.pages}, всего {h.total})", ""]
    if not h.entries:
        lines.append("Пока нет операций.")
    for e in h.entries:
        amount = f"{e.amount:+d} кр." if e.amount else ""
        item = ""
        if e.item_id and e.quantity is not None:
            item = f" {e.quantity:+d} {item_title(e.item_id)}"
        details = ""
        if e.details and e.kind not in ("market_buy", "market_sell", "mine"):
            details = f" · {esc(e.details)}"
        elif e.details in PLANETS:
            details = f" · {planet_title(e.details)}"
        lines.append(
            f"<code>{format_utc(e.created_at)[5:16]}</code> {KIND_LABELS.get(e.kind, esc(e.kind))}"
            f" {amount}{item}{details} → {e.balance_after}"
        )
    return "\n".join(lines)


def offer_text(o: OfferView, now: int) -> str:
    status = {
        "pending": f"⏳ ожидает (ещё {format_duration(o.expires_at - now)})",
        "accepted": "✅ сделка совершена",
        "declined": "❌ отклонено покупателем",
        "cancelled": "🚫 отменено продавцом",
        "expired": "⌛ истекло",
    }[o.status]
    return (
        f"🤝 <b>P2P-предложение #{o.id}</b>\n"
        f"Продавец: {mention(o.seller_id, o.seller_name)}\n"
        f"Покупатель: {mention(o.buyer_id, o.buyer_name)}\n"
        f"Товар: <b>{o.quantity} × {item_title(o.item_id)}</b>\n"
        f"Цена: <b>{o.price}</b> кр. за всё{' (подарок)' if o.price == 0 else ''}\n"
        f"Статус: {status}"
    )


def challenge_text(c: ChallengeView, now: int) -> str:
    status = {
        "pending": f"⏳ ожидает ответа (ещё {format_duration(c.expires_at - now)})",
        "resolved": "⚔️ дуэль состоялась",
        "declined": "❌ отклонён — ставка возвращена",
        "cancelled": "🚫 отменён — ставка возвращена",
        "expired": "⌛ истёк — ставка возвращена",
    }[c.status]
    return (
        f"⚔️ <b>Вызов на дуэль #{c.id}</b>\n"
        f"{mention(c.challenger_id, c.challenger_name)} вызывает {mention(c.target_id, c.target_name)}\n"
        f"Ставка: <b>{c.stake}</b> кр. с каждого\n"
        f"Статус: {status}"
    )


def duel_text(d: DuelResult) -> str:
    c = d.challenge
    a, b = mention(c.challenger_id, c.challenger_name), mention(c.target_id, c.target_name)
    if d.winner_id is None:
        outcome = "🤝 <b>Ничья!</b> Ставки возвращены."
    else:
        winner = a if d.winner_id == c.challenger_id else b
        outcome = f"🏆 Победитель: {winner}" + (f" — выигрыш {2 * c.stake} кр." if c.stake else "")
    xp_note = "\n⭐ XP за дуэль этой пары уже начислялся в течение часа — без XP." if d.xp_capped else ""
    return (
        f"⚔️ <b>Дуэль #{c.id}</b>\n"
        f"{a}: сила {d.challenger_power}, урон −{d.challenger_damage} HP (осталось {d.challenger_hp}), "
        f"+{d.challenger_xp} XP\n"
        f"{b}: сила {d.target_power}, урон −{d.target_damage} HP (осталось {d.target_hp}), "
        f"+{d.target_xp} XP\n"
        f"{outcome}{xp_note}"
    )


def clan_text(v: ClanView) -> str:
    lines = [
        f"🏰 <b>{esc(v.name)}</b> (ID {v.id})",
        f"👑 Лидер: {esc(v.leader_name)}",
        f"👥 Участники: {v.member_count}/{CLAN_MAX_MEMBERS}",
        f"🏦 Казна: <b>{v.treasury}</b> кр.",
        f"🚪 {'Открыт' if v.is_open else 'Закрыт'} для вступления",
    ]
    if v.members:
        lines.append("\n" + ", ".join(("👑 " if uid == v.leader_id else "") + esc(name) for uid, name in v.members))
    return "\n".join(lines)


def enemy_title(enemy_id: str) -> str:
    return ENEMIES[enemy_id].name
