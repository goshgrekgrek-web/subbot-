import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app import cryptobot, db
from app.tribute import Tribute
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
BOT_PATH = "/webhook/telegram"


async def preflight(bot: Bot) -> None:
    """Проверяем всё до старта: токен, канал, Crypto Pay.
    Ошибки ищем в логе, а не в момент первой оплаты."""
    if not config.admin_ids:
        log.warning("ADMIN_IDS пуст — /admin /grant /revoke будут недоступны")

    try:
        me = await bot.get_me()
        log.info("Бот: @%s (id %s)", me.username, me.id)
    except Exception as e:
        log.error("Токен бота не работает: %s", e)

    try:
        chat = await bot.get_chat(config.channel_id)
        log.info("Канал: %s", chat.title)
    except Exception as e:
        log.error("Не вижу канал %s (%s) — добавьте бота админом", config.channel_id, e)

    try:
        app_me = await cryptobot.get_me()
        log.info("Crypto Pay app: %s", app_me.get("name"))
    except Exception as e:
        log.warning("Crypto Pay не отвечает (%s) — проверь CRYPTO_PAY_TOKEN", e)

    tribute_cli = Tribute(config.tribute_api_key)
    if tribute_cli.enabled:
        log.info("Tribute: включён")


async def main() -> None:
    await db.init_db()

    bot = Bot(token=config.bot_token, default=DefaultBotProperties())
    dp = Dispatcher()
    dp.include_router(router)

    await preflight(bot)

    if not config.public_base_url:
        raise RuntimeError(
            "Домен не задан. Включите «Использовать домен» в панели Bothost "
            "либо выставьте PUBLIC_BASE_URL и USE_WEBHOOK=0 для polling."
        )

    # наш aiohttp-app: вебхуки CryptoPay, Tribute, /health
    app = build_app(bot, DEFAULT_PLAN_DAYS)

    if config.use_webhook:
        # Telegram-апдейты идут через тот же сервер, отдельного polling нет
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=BOT_PATH)
        setup_application(app, dp, bot=bot)
        await bot.set_webhook(
            f"{config.public_base_url}{BOT_PATH}",
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info("Telegram webhook: %s%s", config.public_base_url, BOT_PATH)
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Режим polling: Telegram опрашиваем сами, сервер только для вебхуков оплат")

    runner = web.AppRunner(app)
    await runner.setup()
    # 0.0.0.0 обязательно: прокси Bothost стучится извне контейнера,
    # на 127.0.0.1 он ничего не найдёт → 502.
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    log.info("HTTP слушает 0.0.0.0:%s", config.port)

    sched = asyncio.create_task(scheduler_loop(bot))
    if not config.use_webhook:
        sched_poll = asyncio.create_task(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        )
    else:
        sched_poll = None

    try:
        await asyncio.Event().wait()   # живём, пока процесс не убьют
    finally:
        sched.cancel()
        if sched_poll:
            sched_poll.cancel()
        await runner.cleanup()
        await cryptobot.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
