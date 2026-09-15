"""Выдача и отзыв доступа в закрытый канал."""
from __future__ import annotations
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.config import config
from app import db

log = logging.getLogger(__name__)


async def make_join_request_link(bot: Bot, tg_id: int, days: int) -> str:
    """Ссылка создаёт заявку на вступление. Бот одобрит её автоматически,
    только если у пользователя есть действующая подписка CryptoBot."""
    try:
        await bot.unban_chat_member(
            chat_id=config.channel_id, user_id=tg_id, only_if_banned=True
        )
    except TelegramBadRequest as e:
        log.debug("unban %s: %s", tg_id, e)

    link = await bot.create_chat_invite_link(
        chat_id=config.channel_id,
        creates_join_request=True,
        name=f"crypto_sub_{tg_id}_{days}d",
    )
    return link.invite_link


# Совместимость со старым кодом.
make_invite_link = make_join_request_link


async def approve_paid_join(bot: Bot, tg_id: int) -> bool:
    """Одобряет заявку, только если есть активная CryptoBot-подписка."""
    sub = await db.active_subscription(tg_id, "cryptobot")
    if not sub:
        return False
    try:
        await bot.approve_chat_join_request(config.channel_id, tg_id)
        await db.audit("bot", "join_request_approved", tg_id, "cryptobot")
        return True
    except TelegramBadRequest as e:
        log.warning("не смог одобрить заявку %s: %s", tg_id, e)
        return False


async def revoke_access(bot: Bot, tg_id: int) -> None:
    """Удалить пользователя из канала. При новой оплате ban будет снят."""
    try:
        await bot.ban_chat_member(
            chat_id=config.channel_id,
            user_id=tg_id,
            revoke_messages=False,
        )
    except TelegramBadRequest as e:
        log.warning("не смог исключить %s: %s", tg_id, e)


async def has_any_paid_access(tg_id: int) -> bool:
    """Есть ли действующая подписка любого учтённого источника."""
    return await db.active_subscription(tg_id) is not None
