"""
Клиент Crypto Pay (@CryptoBot).

Два режима:
  1. Исходящие платежи: createInvoice()
  2. Входящие вебхуки: verify_webhook() + parse_payment()
"""
from __future__ import annotations
import hashlib
import hmac
import logging

import aiohttp

from app.config import config

API = "https://pay.crypt.bot/api"
log = logging.getLogger(__name__)


class CryptoPayClient:
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

    async def _post(self, path: str, **data):
        s = await self._s()
        async with s.post(f"{API}{path}", json=data) as r:
            r.raise_for_status()
            return await r.json()

    async def get_me(self):
        """Получить информацию о приложении."""
        result = await self._post("/getMe")
        return result.get("result", {})

    async def create_invoice(self, amount: str, asset: str, **kwargs):
        """Создать инвойс для оплаты."""
        payload = {"amount": amount, "asset": asset, **kwargs}
        result = await self._post("/createInvoice", **payload)
        return result.get("result", {})

    async def get_invoices(self, invoice_ids: list = None, **kwargs):
        """Получить список инвойсов."""
        payload = kwargs.copy()
        if invoice_ids:
            payload["invoice_ids"] = ",".join(map(str, invoice_ids))
        result = await self._post("/getInvoices", **payload)
        return result.get("result", {})


cryptobot = CryptoPayClient(config.crypto_token)


def verify_webhook(body: bytes, signature: str) -> bool:
    """Заголовок crypto-pay-api-signature: HMAC-SHA256(SHA256(token), body)."""
    if not signature or not config.crypto_token:
        return False
    token_hash = hashlib.sha256(config.crypto_token.encode()).digest()
    calc = hmac.new(token_hash, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature.strip())


def parse_payment(payload: dict) -> dict | None:
    """Вытаскиваем информацию из вебхука Crypto Pay.

    Структура: {"update_id": ..., "update_type": "invoice_paid", "payload": {...}}
    """
    if payload.get("update_type") != "invoice_paid":
        return None
    inv = payload.get("payload") or {}
    return {
        "invoice_id": inv.get("invoice_id"),
        "amount": inv.get("amount"),
        "asset": inv.get("asset"),
        "status": inv.get("status"),
        "paid_at": inv.get("paid_at"),
        "payload": inv.get("payload"),  # наше description
    }
