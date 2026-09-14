import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from app import cryptobot, db, tribute
from app.config import config
from app.handlers import router
from app.scheduler import scheduler_loop
from app.webhooks import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("subbot")

DEFAULT_PLAN_DAYS = 30


async def main() -> None:
    await db.init_db()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Проверяем, что токены и права на месте — до старта, а не в момент оплаты.
    if not config.admin_ids:
        log.warning("ADMIN_IDS пуст — команды /admin /grant /revoke будут недоступны")
    try:
        me = await bot.get_me()
        log.info("Бот: @%s (id %s)", me.username, me.id)
        chat = await bot.get_chat(config.channel_id)
        log.info("Канал: %s", chat.title)
    except Exception as e:
        log.error("Не смог получить данные о боте/канале: %s", e)

    try:
        app_me = await cryptobot.get_me()
        log.info("Crypto Pay app: %s", app_me.get("name"))
    except Exception as e:
        log.warning("Crypto Pay не отвечает (%s) — проверь CRYPTO_PAY_TOKEN", e)

    if tribute.enabled:
        log.info("Tribute: включён")

    app = build_app(bot, DEFAULT_PLAN_DAYS)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    log.info("Вебхуки на %s:%s", config.public_base_url, config.port)

    sched = asyncio.create_task(scheduler_loop(bot))

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sched.cancel()
        await runner.cleanup()
        await cryptobot.close()
        await tribute.close()


if __name__ == "__main__":
    asyncio.run(main())
