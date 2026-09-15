from __future__ import annotations
import logging
import asyncio
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton

from app.cryptobot import cryptobot
from app import access, db, tribute
from app.config import config
from app.keyboards import (sub_keyboard, tariff_keyboard, crypto_tariff_keyboard,
                           broadcast_pay_keyboard, broadcast_confirm_keyboard)

log = logging.getLogger(__name__)
router = Router()

CRYPTO_PRICES = {30: "11", 90: "33", 365: "133"}


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def _price(days: int) -> str:
    try:
        return CRYPTO_PRICES[days]
    except KeyError:
        raise ValueError(f"Неизвестный тариф: {days} дней")


async def _status_text(tg_id: int) -> str:
    active = []
    for source in ("cryptobot", "tribute"):
        sub = await db.active_subscription(tg_id, source)
        if sub:
            active.append(sub)

    if not active:
        return (
            "👋 <b>Привет!</b>\n\n"
            "Здесь ты можешь оформить подписку на мой закрытый Telegram-канал "
            "<b>DeluxePRV</b>.\n\n"
            "💳 Стоимость подписки на 1 месяц — <b>1000 ₽ / 11 USDT</b>.\n\n"
            "👇 <b>Выбери удобный способ оплаты:</b>"
        )

    # Пользователю не важно, через какого провайдера оплачено:
    # показываем единый статус канала и самую позднюю активную дату.
    expires_at = max(sub["expires_at"] for sub in active)
    return (
        "💎 <b>DeluxePRV</b>\n\n"
        "✅ Подписка на канал активна\n"
        f"📅 Доступ до: <b>{_fmt(expires_at)}</b>"
    )


@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject) -> None:
    await db.upsert_user(message.from_user.id, message.from_user.username)
    text = await _status_text(message.from_user.id)
    active = (
        await db.active_subscription(message.from_user.id, "cryptobot")
        or await db.active_subscription(message.from_user.id, "tribute")
    )
    if active:
        text += "\n\n👇 <b>Продлить подписку:</b>"
    await message.answer(
        text,
        reply_markup=sub_keyboard(_price(30), config.crypto_asset),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "start")
async def cb_start(cb: CallbackQuery) -> None:
    text = await _status_text(cb.from_user.id)
    active = (
        await db.active_subscription(cb.from_user.id, "cryptobot")
        or await db.active_subscription(cb.from_user.id, "tribute")
    )
    if active:
        text += "\n\n👇 <b>Продлить подписку:</b>"
    await cb.message.answer(
        text,
        reply_markup=sub_keyboard(_price(30), config.crypto_asset),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "status")
async def cb_status(cb: CallbackQuery) -> None:
    await cb.message.answer(await _status_text(cb.from_user.id), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "paymethod:crypto")
async def cb_crypto_method(cb: CallbackQuery) -> None:
    await cb.message.answer(
        "Выбери тариф CryptoBot:",
        reply_markup=crypto_tariff_keyboard(),
    )
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

    await db.save_payment("cryptobot", inv["invoice_id"], tg_id,
                          price, config.crypto_asset, "pending", plan_days=days)
    from app.state import PLAN_BY_INVOICE
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
    result = await cryptobot.get_invoices([inv_id])
    # Crypto Pay getInvoices возвращает {"items": [...]}
    if isinstance(result, dict):
        invoices = result.get("items") or []
    elif isinstance(result, list):
        invoices = result
    else:
        invoices = []

    if not invoices:
        await cb.message.answer("Счёт не найден.")
        return
    inv = invoices[0]
    if inv.get("status") == "paid":
        tg_id = int(inv.get("payload") or cb.from_user.id)
        payment = await db.get_payment("cryptobot", str(inv_id))
        days = int(payment["plan_days"]) if payment and payment["plan_days"] else _days_for(inv_id)
        await db.add_subscription(tg_id, "cryptobot", str(inv_id), days)
        await db.save_payment("cryptobot", inv_id, tg_id,
                              inv.get("amount"), inv.get("asset"), "paid")
        link = await access.make_join_request_link(cb.bot, tg_id, days)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Вступить в DeluxePRV", url=link)
        ]])
        await cb.message.answer(
            "✅ Оплата найдена! Подписка активна.\n\n"
            "Нажми кнопку ниже — бот автоматически примет твою заявку в канал.",
            reply_markup=kb,
        )
    else:
        await cb.message.answer(f"Пока не оплачен (статус: {inv.get('status')}). "
                                "Попробуй через минуту.")


def _days_for(invoice_id: int) -> int:
    from app.state import PLAN_BY_INVOICE
    return PLAN_BY_INVOICE.get(str(invoice_id), 30)


@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest) -> None:
    if req.chat.id != config.channel_id:
        return
    tg_id = req.from_user.id
    if await access.approve_paid_join(req.bot, tg_id):
        try:
            await req.bot.send_message(
                tg_id,
                "✅ Добро пожаловать в DeluxePRV! Доступ активирован."
            )
        except Exception:
            pass
    else:
        try:
            await req.bot.decline_chat_join_request(config.channel_id, tg_id)
            await req.bot.send_message(
                tg_id,
                "Подписка CryptoBot не найдена. Оформить доступ можно через /start."
            )
        except Exception:
            pass



class BroadcastState(StatesGroup):
    waiting_post = State()
    waiting_confirm = State()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    await state.clear()
    await state.set_state(BroadcastState.waiting_post)
    await message.answer(
        "📣 <b>Новая рассылка</b>\n\n"
        "Отправь мне <b>одно фото с подписью</b> — именно так пост будет выглядеть "
        "у пользователей.\n\n"
        "Я покажу предпросмотр и только после твоего подтверждения отправлю его всем.",
        parse_mode="HTML",
    )


@router.message(BroadcastState.waiting_post, F.photo)
async def broadcast_get_post(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    photo_id = message.photo[-1].file_id
    caption = message.caption or ""
    caption_entities = message.caption_entities or []

    await state.update_data(
        photo_id=photo_id,
        caption=caption,
        caption_entities=caption_entities,
    )
    await state.set_state(BroadcastState.waiting_confirm)

    await message.answer("👀 <b>Предпросмотр:</b>", parse_mode="HTML")
    await message.answer_photo(
        photo=photo_id,
        caption=caption or None,
        caption_entities=caption_entities or None,
        reply_markup=broadcast_pay_keyboard(),
    )
    await message.answer(
        "Отправляем этот пост всем пользователям бота?",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.message(BroadcastState.waiting_post)
async def broadcast_need_photo(message: Message) -> None:
    if message.from_user.id not in config.admin_ids:
        return
    await message.answer("Пришли именно <b>фото с подписью</b> одним сообщением.", parse_mode="HTML")


@router.callback_query(BroadcastState.waiting_confirm, F.data == "broadcast:cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in config.admin_ids:
        return
    await state.clear()
    await cb.message.edit_text("❌ Рассылка отменена.")
    await cb.answer()


@router.callback_query(BroadcastState.waiting_confirm, F.data == "broadcast:send")
async def broadcast_send(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in config.admin_ids:
        return

    data = await state.get_data()
    photo_id = data.get("photo_id")
    caption = data.get("caption") or None
    caption_entities = data.get("caption_entities") or None

    if not photo_id:
        await state.clear()
        await cb.answer("Пост не найден. Запусти /broadcast заново.", show_alert=True)
        return

    # Сразу закрываем состояние, чтобы двойной клик не запустил вторую рассылку.
    await state.clear()
    await cb.message.edit_text("⏳ Рассылка запущена…")
    await cb.answer()

    user_ids = await db.all_user_ids()
    sent = 0
    failed = 0

    for tg_id in user_ids:
        try:
            await cb.bot.send_photo(
                chat_id=tg_id,
                photo=photo_id,
                caption=caption,
                caption_entities=caption_entities,
                reply_markup=broadcast_pay_keyboard(),
            )
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1
            log.exception("Ошибка рассылки пользователю %s", tg_id)

        # Консервативно держимся ниже массовых лимитов Telegram.
        await asyncio.sleep(0.06)

    await cb.bot.send_message(
        cb.from_user.id,
        "✅ <b>Рассылка завершена</b>\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
        f"🚫 Не доставлено: <b>{failed}</b>\n"
        f"👥 Всего в базе: <b>{len(user_ids)}</b>",
        parse_mode="HTML",
    )


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
