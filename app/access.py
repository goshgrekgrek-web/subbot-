"""Выдача и отзыв доступа в закрытый канал."""
from __future__ import annotations
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.config import config
from app import db

log = logging.getLogger(__name__)

MAX_INVITE_LINK_TTL = 30 * 60  # ссылка живёт 30 минут


async def make_invite_link(bot: Bot, tg_id: int, days: int) -> str:
    """Одноразовая ссылка. Перед новым инвайтом снимаем старый бан,
    иначе Telegram не пустит пользователя обратно после истечения подписки."""
    try:
        await bot.unban_chat_member(
            chat_id=config.channel_id, user_id=tg_id, only_if_banned=True
        )
    except TelegramBadRequest as e:
        log.debug("unban %s: %s", tg_id, e)

    link = await bot.create_chat_invite_link(
        chat_id=config.channel_id,
        member_limit=1,                                     # вступить сможет ровно один
        expire_date=int(time.time()) + MAX_INVITE_LINK_TTL,
        name=f"sub_{tg_id}_{days}d",
    )
    return link.invite_link


async def revoke_access(bot: Bot, tg_id: int) -> None:
    """Убрать из канала, но НЕ навсегда: Telegram снимет бан автоматически
    в until_date, поэтому повторная оплата сработает через unban(only_if_banned)."""
    try:
        await bot.ban_chat_member(
            chat_id=config.channel_id,
            user_id=tg_id,
            revoke_messages=False,
        )
    except TelegramBadRequest as e:
        log.warning("не смог исключить %s: %s", tg_id, e)


async def has_any_paid_access(tg_id: int) -> bool:
    """Учитываем оба источника: если человек платит через Tribute,
    наш бан за неоплаченный CryptoBot-инвойс его не должен выкидывать."""
    return await db.active_subscription(tg_id) is not None
