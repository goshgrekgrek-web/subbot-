"""Клиент Tribute (tribute.tg) + проверка подписи вебхуков.

Два режима интеграции:
  A. Tribute сам управляет доступом в канал — вы добавляете @tribute бота админом
     и создаёте подписку в Creator Dashboard. Наш бот только слушает вебхуки
     (для аналитики, приветствий, общей базы).
  B. Свой чекаут через Shop API: /products -> цена -> /products/{id}/purchase
     -> pay_url. Доступом управляем мы.
Ниже — режим A, он надёжнее: Tribute сам гоняет инвайты и продления.
"""
from __future__ import annotations
import hashlib
import hmac
import logging

import aiohttp

from app.config import config

API = "https://tribute.tg/api/v1"
log = logging.getLogger(__name__)


class Tribute:
    def __init__(self, api_key: str):
        self._key = api_key
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Api-Key": self._key},
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str):
        s = await self._s()
        async with s.get(f"{API}{path}") as r:
            r.raise_for_status()
            return await r.json()

    async def subscriptions(self, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        return await self._get(f"/subscriptions?{q}")

    async def products(self):
        return await self._get("/products")


def verify_webhook(body: bytes, signature: str) -> bool:
    """Заголовок trbt-signature: HMAC-SHA256 тела запроса вашим API key."""
    if not signature or not config.tribute_webhook_secret:
        return False
    calc = hmac.new(
        config.tribute_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    # Tribute может отдавать подпись с префиксом/в hex или base64 — сравниваем hex
    return hmac.compare_digest(calc, signature.strip())


def parse_subscription_event(payload: dict) -> dict | None:
    """Вытаскиваем tg_id и срок из события Tribute.

    Имена полей у Tribute менялись между версиями API, поэтому пробуем
    несколько вариантов — так интеграция не отвалится на очередном апдейте.
    """
    sub = payload.get("subscription") or payload.get("payload") or payload
    if not isinstance(sub, dict):
        return None

    tg_id = (
        sub.get("telegram_user_id")
        or sub.get("telegram_id")
        or (sub.get("user") or {}).get("telegram_id")
        or (sub.get("subscriber") or {}).get("telegram_id")
    )
    if tg_id is None:
        log.warning("Tribute: не нашёл tg_id в событии: %s", list(sub.keys()))
        return None

    sub_id = sub.get("id") or sub.get("subscription_id") or payload.get("id")
    days = sub.get("period_days") or sub.get("duration_days")
    expires = sub.get("expires_at") or sub.get("expiration_date")

    return {
        "tg_id": int(tg_id),
        "subscription_id": str(sub_id) if sub_id is not None else "",
        "type": payload.get("type") or sub.get("type") or "regular",
        "days": int(days) if days else None,
        "expires_at": str(expires) if expires else None,
    }
