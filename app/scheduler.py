import asyncio
import logging

from aiogram import Bot

from app import access, db

log = logging.getLogger(__name__)

TICK = 300  # каждые 5 минут


async def _kick_expired(bot: Bot) -> None:
    # Tribute удаляет своих подписчиков сам. Здесь управляем только CryptoBot.
    for sub in await db.expired_batch(source="cryptobot"):
        tg_id = sub["tg_id"]
        await db.mark_expired(sub["id"])

        # Если есть другая действующая подписка, например Tribute, не удаляем.
        if await access.has_any_paid_access(tg_id):
            continue

        await access.revoke_access(bot, tg_id)
        await db.audit("scheduler", "subscription_expired", tg_id, "cryptobot")
        try:
            await bot.send_message(
                tg_id,
                "⏳ Подписка CryptoBot закончилась, доступ к DeluxePRV закрыт.\n\n"
                "Чтобы продлить подписку, нажми /start.",
            )
        except Exception:
            pass


async def _send_reminder(bot: Bot, sub, key: str, text: str) -> None:
    if not await db.claim_reminder(sub["id"], key):
        return
    try:
        await bot.send_message(sub["tg_id"], text)
        await db.audit("scheduler", f"expiry_reminder_{key}", sub["tg_id"], "cryptobot")
    except Exception as e:
        log.warning("Не доставил напоминание %s: %s", sub["tg_id"], e)


async def _remind(bot: Bot) -> None:
    # Окна шириной 10 минут при цикле 5 минут.
    for sub in await db.expiring_soon(
        3 * 86400 - 300, 3 * 86400 + 300, source="cryptobot"
    ):
        await _send_reminder(
            bot, sub, "3d",
            "🔔 Подписка DeluxePRV закончится через 3 дня.\n"
            "Продли сейчас, чтобы не потерять доступ — /start",
        )

    for sub in await db.expiring_soon(
        86400 - 300, 86400 + 300, source="cryptobot"
    ):
        await _send_reminder(
            bot, sub, "1d",
            "⚠️ Подписка DeluxePRV закончится примерно через 1 день.\n"
            "Продлить подписку можно здесь — /start",
        )


async def scheduler_loop(bot: Bot) -> None:
    log.info("Планировщик запущен")
    while True:
        try:
            await _kick_expired(bot)
            await _remind(bot)
        except Exception as e:
            log.exception("Планировщик упал на итерации: %s", e)
        await asyncio.sleep(TICK)
