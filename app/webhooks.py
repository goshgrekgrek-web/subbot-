"""Приём вебхуков: Crypto Pay (@CryptoBot) и Tribute. Один aiohttp-сервер."""
from __future__ import annotations
import logging

from aiohttp import web
from aiogram import Bot

from app import access, cryptobot, db, tribute
from app.keyboards import sub_keyboard

log = logging.getLogger(__name__)


async def cryptopay_webhook(request: web.Request) -> web.Response:
    body = await request.read()
    signature = request.headers.get("crypto-pay-api-signature", "")
    if not cryptobot.verify_webhook(body, signature):
        log.warning("CryptoPay: плохая подпись, отбой")
        return web.Response(status=401)

    update = await request.json()

    # Всегда 200, иначе CryptoPay будет ретраить сутки.
    if update.get("update_type") != "invoice_paid":
        return web.Response(status=200)

    inv = update["payload"]
    event_id = f"inv_{inv['invoice_id']}"
    if not await db.claim_event("cryptobot", event_id):
        return web.Response(status=200)   # дубль

    try:
        tg_id = int(inv.get("payload") or 0)
    except (TypeError, ValueError):
        log.error("CryptoPay: нет tg_id в payload инвойса %s", inv.get("invoice_id"))
        return web.Response(status=200)

    if not tg_id:
        return web.Response(status=200)

    payment = await db.get_payment("cryptobot", str(inv["invoice_id"]))
    days = int(payment["plan_days"]) if payment and payment["plan_days"] else request.app["plan_days"]
    bot: Bot = request.app["bot"]

    expiry = await db.add_subscription(tg_id, "cryptobot", str(inv["invoice_id"]), days)
    await db.save_payment("cryptobot", inv["invoice_id"], tg_id,
                          inv.get("amount"), inv.get("asset"), "paid", plan_days=days)
    await db.audit("cryptobot", "subscription_activated", tg_id,
                   f"{days}d, inv={inv['invoice_id']}")

    try:
        link = await access.make_join_request_link(bot, tg_id, days)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Вступить в DeluxePRV", url=link)
        ]])
        await bot.send_message(
            tg_id,
            f"✅ Оплата получена — подписка активна до <b>{_fmt(expiry)}</b>.\n\n"
            "Нажми кнопку ниже. Заявка в канал будет принята автоматически.",
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as e:  # не роняем вебхук из-за доставки
        log.exception("Не смог отправить ссылку %s: %s", tg_id, e)
        await db.audit("system", "invite_delivery_failed", tg_id, str(e))
        for admin in request.app["admin_ids"]:
            try:
                await bot.send_message(admin, f"⚠️ Не доставил инвайт {tg_id}: {e}")
            except Exception:
                pass

    return web.Response(status=200)


async def tribute_webhook(request: web.Request) -> web.Response:
    body = await request.read()
    if not tribute.verify_webhook(body, request.headers.get("trbt-signature", "")):
        log.warning("Tribute: плохая подпись")
        return web.Response(status=401)

    payload = await request.json()
    name = payload.get("name") or payload.get("event") or ""

    # Наш бот доступом не управляет (это делает сам Tribute) — только учёт.
    if name in ("new_subscription", "renewed_subscription"):
        info = tribute.parse_subscription_event(payload)
        if info:
            await db.upsert_user(info["tg_id"], None)
            await db.save_payment("tribute", info["subscription_id"],
                                  info["tg_id"], None, None, "paid",
                                  plan_days=info.get("days"))
            if info.get("expires_at"):
                await db.upsert_subscription_until(
                    info["tg_id"], "tribute", str(info["subscription_id"]),
                    int(info.get("days") or 30), int(info["expires_at"])
                )
            await db.audit("tribute", name, info["tg_id"], str(info))
            log.info("Tribute %s: %s", name, info)

    elif name == "cancelled_subscription":
        info = tribute.parse_subscription_event(payload)
        if info:
            await db.cancel_subscription(info["tg_id"], "tribute")
            await db.audit("tribute", "cancelled", info["tg_id"])

    return web.Response(status=200)


def _fmt(ts: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def build_app(bot: Bot, plan_days: int) -> web.Application:
    from app.config import config
    app = web.Application()
    app["bot"] = bot
    app["plan_days"] = plan_days
    app["admin_ids"] = config.admin_ids
    app.add_routes([
        web.post("/webhook/cryptopay", cryptopay_webhook),
        web.post("/webhook/tribute", tribute_webhook),
        web.get("/health", lambda r: web.json_response({"ok": True})),
    ])
    return app
