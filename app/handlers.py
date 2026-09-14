from __future__ import annotations
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from app import access, cryptobot, db, tribute
from app.config import config
from app.keyboards import sub_keyboard, tariff_keyboard

log = logging.getLogger(__name__)
router = Router()

PRICES = {30: 1.0, 90: 3.6}          # множитель к базовой цене


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def _price(days: int) -> str:
    base = float(config.crypto_price)
    total = base * (days / 30) * (1.0 if days == 30 else 0.8)
    return f"{total:g}"


async def _status_text(tg_id: int) -> str:
    rows = []
    for src, label in (("cryptobot", "💎 CryptoBot"), ("tribute", "🎁 Tribute")):
        sub = await db.active_subscription(tg_id, src)
        if sub:
            rows.append(f"{label}: активна до <b>{_fmt(sub['expires_at'])}</b>")
    if not rows:
        return "У тебя пока нет активной подписки."
    return "Твой доступ:\n" + "\n".join(rows)


@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject) -> None:
    await db.upsert_user(message.from_user.id, message.from_user.username)

    # deep-link оплаты: /start pay_30
    if command.args and command.args.startswith("pay_"):
        try:
            days = int(command.args.split("_", 1)[1])
            await _send_invoice(message, days)
            return
        except (ValueError, IndexError):
            pass

    active = await db.active_subscription(message.from_user.id)
    if active:
        await message.answer(
            f"✅ Доступ уже открыт.\n\n{await _status_text(message.from_user.id)}\n\n"
            "Продлить можно той же кнопкой — дни просто сложатся.",
            reply_markup=sub_keyboard(_price(30), config.crypto_asset),
            parse_mode="HTML",
        )
        return

    await message.answer(
        "👋 Привет! Здесь оформляется подписка на закрытый канал.\n\n"
        "Оплата — криптой через @CryptoBot, моментально и без регистрации.\n"
        "После оплаты бот сразу пришлёт одноразовую ссылку в канал.",
        reply_markup=tariff_keyboard(),
    )
    await message.answer("Выбери тариф:",
                         reply_markup=sub_keyboard(_price(30), config.crypto_asset))


@router.callback_query(F.data == "start")
async def cb_start(cb: CallbackQuery) -> None:
    await cb.message.answer("Выбери тариф:",
                            reply_markup=sub_keyboard(_price(30), config.crypto_asset))
    await cb.answer()


@router.callback_query(F.data == "status")
async def cb_status(cb: CallbackQuery) -> None:
    await cb.message.answer(await _status_text(cb.from_user.id), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery) -> None:
    days = int(cb.data.split(":")[1])
    await cb.message.answer("Готовлю счёт…")
    await cb.answer()
    await _send_invoice(cb.message, days, tg_id=cb.from_user.id)


async def _send_invoice(message: Message, days: int, tg_id: int | None = None) -> None:
    tg_id = tg_id or message.from_user.id
    price = _price(days)
    inv = await cryptobot.create_invoice(amount=price, asset=config.crypto_asset, description=str(tg_id))

    # фиксируем цену инвойса, чтобы вебхук знал срок подписки
    await db.save_payment("cryptobot", inv["invoice_id"], tg_id,
                          price, config.crypto_asset, "pending")
    from app.webhooks import PLAN_BY_INVOICE
    PLAN_BY_INVOICE[str(inv["invoice_id"])] = days
    await db.audit("bot", "invoice_created", tg_id,
                   f"inv={inv['invoice_id']} days={days} price={price}")

    from app.keyboards import pay_keyboard
    await message.answer(
        f"🧾 Счёт на <b>{price} {config.crypto_asset}</b> за {days} дней.\n\n"
        f"Оплати по кнопке ниже — обычно это занимает меньше минуты.\n"
        f"Если оплатил, нажми «Я оплатил» или просто подожди: бот пришлёт ссылку сам.",
        parse_mode="HTML",
        reply_markup=pay_keyboard(inv["pay_url"], inv["invoice_id"]),
    )


@router.callback_query(F.data.startswith("check:"))
async def cb_check(cb: CallbackQuery) -> None:
    """Ручная проверка на случай, если вебхук не дошёл."""
    inv_id = int(cb.data.split(":")[1])
    await cb.answer("Проверяю…")
    invoices = await cryptobot.get_invoices([inv_id])
    if not invoices:
        await cb.message.answer("Счёт не найден.")
        return
    inv = invoices[0]
    if inv.get("status") == "paid":
        tg_id = int(inv.get("payload") or cb.from_user.id)
        days = _days_for(inv_id)
        await db.add_subscription(tg_id, "cryptobot", str(inv_id), days)
        await db.save_payment("cryptobot", inv_id, tg_id,
                              inv.get("amount"), inv.get("asset"), "paid")
        link = await access.make_invite_link(cb.bot, tg_id, days)
        await cb.message.answer(f"✅ Оплата найдена!\n\nСсылка в канал:\n{link}",
                                disable_web_page_preview=True)
    else:
        await cb.message.answer(f"Пока не оплачен (статус: {inv.get('status')}). "
                                "Попробуй через минуту.")


def _days_for(invoice_id: int) -> int:
    from app.state import PLAN_BY_INVOICE
    return PLAN_BY_INVOICE.get(str(invoice_id), 30)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user.id not in config.admin_ids:
        return
    s = await db.stats()
    await message.answer(
        f"📊 <b>Статистика</b>\n"
        f"Пользователей: {s['users']}\n"
        f"Активных подписок: {s['active']}\n"
        f"Оплат всего: {s['paid']} (CryptoBot: {s['ico']}, Tribute: {s['tribute']})",
        parse_mode="HTML",
    )


@router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject) -> None:
    """Выдать доступ вручную: /grant 123456789 30"""
    if message.from_user.id not in config.admin_ids:
        return
    try:
        tg_id, days = map(int, command.args.split())
    except (ValueError, AttributeError):
        await message.answer("Формат: /grant <tg_id> <дней>")
        return
    await db.add_subscription(tg_id, "manual", f"admin_{message.from_user.id}", days)
    await db.audit(str(message.from_user.id), "manual_grant", tg_id, f"{days}d")
    link = await access.make_invite_link(message.bot, tg_id, days)
    await message.answer(f"Выдал {tg_id} на {days} дн.\nСсылка:\n{link}",
                         disable_web_page_preview=True)
    try:
        await message.bot.send_message(
            tg_id, f"🎁 Тебе выдали доступ на {days} дней.\n\nСсылка в канал:\n{link}",
            disable_web_page_preview=True)
    except Exception:
        pass


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject) -> None:
    """Досрочно снять доступ: /revoke 123456789"""
    if message.from_user.id not in config.admin_ids:
        return
    try:
        tg_id = int(command.args)
    except (ValueError, TypeError):
        await message.answer("Формат: /revoke <tg_id>")
        return
    ok = await db.cancel_subscription(tg_id, "manual") or \
         await db.cancel_subscription(tg_id, "cryptobot") or \
         await db.cancel_subscription(tg_id, "tribute")
    await access.revoke_access(message.bot, tg_id)
    await db.audit(str(message.from_user.id), "revoke", tg_id)
    await message.answer("Доступ снят." if ok else "Активной подписки не было, но из канала убрал.")


@router.pre_checkout_query()
async def precheckout(q: PreCheckoutQuery) -> None:
    """Заглушка на будущее — если решите добавить оплату Telegram Stars в нашем боте."""
    await q.answer(ok=True)
