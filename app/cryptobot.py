"""Клиент Crypto Pay API (@CryptoBot)."""
from __future__ import annotations
import hashlib
import hmac
import logging

import aiohttp

from app.config import config

API = "https://pay.crypt.bot/api"
log = logging.getLogger(__name__)


class CryptoPay:
    def __init__(self, token: str):
        self._token = token
        self._session: aiohttp.ClientSession | None = None

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Crypto-Pay-API-Token": self._token},
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _call(self, method: str, **params):
        s = await self._s()
        async with s.post(f"{API}/{method}", json=params) as r:
            data = await r.json()
        if not data.get("ok"):
            raise RuntimeError(f"CryptoPay {method}: {data}")
        return data["result"]

    async def get_me(self):
        return await self._call("getMe")

    async def create_invoice(self, tg_id: int, days: int) -> dict:
        """Возвращает {invoice_id, pay_url}. Именно pay_url, не mini_app_invoice_url:
        обычная ссылка открывается на любом устройстве."""
        return await self._call(
            "createInvoice",
            currency_type=config.crypto_currency_type,   # 'crypto' | 'fiat'
            asset=config.crypto_asset,
            amount=config.crypto_price,
            description=f"Подписка на {days} дн.",
            payload=str(tg_id),                          # сюда кладём tg_id
            expires_in=3600,
            allow_comments=False,
            allow_anonymous=False,
        )

    async def get_invoices(self, invoice_ids: list[int]) -> list[dict]:
        return await self._call("getInvoices", invoice_ids=",".join(map(str, invoice_ids)))

    async def get_balance(self):
        return await self._call("getBalance")


def verify_webhook(body: bytes, signature: str) -> bool:
    """crypto-pay-api-signature = HMAC-SHA256(sha256(token), body)."""
    if not signature:
        return False
    secret = hashlib.sha256(config.crypto_token.encode()).digest()
    calc = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)


crypto = CryptoPay(config.crypto_token)
