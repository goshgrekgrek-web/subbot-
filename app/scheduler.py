import asyncio
import logging

from aiogram import Bot

from app import access, db

log = logging.getLogger(__name__)

WARN_WINDOW = 3 * 86400      # за 3 дня до конца
TICK = 300                   # проверка раз в 5 минут


async def _kick_expired(bot: Bot) -> None:
    for sub in await db.expired_batch():
        tg_id = sub["tg_id"]
        # Не выкидываем, если у человека живой доступ из другого источника (Tribute).
        if await access.has_any_paid_access(tg_id):
            await db.mark_expired(sub["id"])
            continue

        await access.revoke_access(bot, tg_id)
        await db.mark_expired(sub["id"])
        await db.audit("scheduler", "subscription_expired", tg_id, sub["source"])
        try:
            await bot.send_message(
                tg_id,
                "⏳ Подписка закончилась, доступ к каналу закрыт.\n\n"
                "Продлить можно в любой момент — жми /start, "
                "вернём в канал за минуту.",
            )
        except Exception:
            pass


async def _remind(bot: Bot) -> None:
    # окно [2d, 3d] — чтобы не спамить каждые 5 минут
    for sub in await db.expiring_soon(2 * 86400, WARN_WINDOW):
        tg_id = sub["tg_id"]
        try:
            await bot.send_message(
                tg_id,
                "🔔 Напоминание: подписка истекает через 3 дня.\n"
                "Продли сейчас, чтобы не терять доступ — /start",
            )
            await db.audit("scheduler", "expiry_reminder", tg_id)
        except Exception:
            pass


async def scheduler_loop(bot: Bot) -> None:
    log.info("Планировщик запущен")
    while True:
        try:
            await _kick_expired(bot)
            await _remind(bot)
        except Exception as e:
            log.exception("Планировщик упал на итерации: %s", e)
        await asyncio.sleep(TICK)
