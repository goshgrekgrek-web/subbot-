import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    channel_id: int              # приватный канал, напр. -1001234567890
    public_base_url: str         # https://sub.example.com — HTTPS обязателен

    crypto_token: str            # Crypto Pay API token (@CryptoBot -> Crypto Pay -> My Apps)
    crypto_asset: str            # USDT / TON / BTC
    crypto_price: str            # цена в этой валюте, строкой: "5"
    crypto_currency_type: str    # "crypto" или "fiat"

    tribute_api_key: str         # Creator Dashboard -> ... -> API Keys
    tribute_webhook_secret: str  # тот же API key (им подписываются вебхуки)

    admin_ids: tuple[int, ...]
    db_path: str
    port: int


def _ids(raw: str) -> tuple[int, ...]:
    return tuple(int(x.strip()) for x in raw.split(",") if x.strip())


config = Config(
    bot_token=os.environ["BOT_TOKEN"],
    channel_id=int(os.environ["CHANNEL_ID"]),
    public_base_url=os.environ["PUBLIC_BASE_URL"].rstrip("/"),
    crypto_token=os.environ["CRYPTO_PAY_TOKEN"],
    crypto_asset=os.getenv("CRYPTO_ASSET", "USDT"),
    crypto_price=os.getenv("CRYPTO_PRICE", "5"),
    crypto_currency_type=os.getenv("CRYPTO_CURRENCY_TYPE", "crypto"),
    tribute_api_key=os.getenv("TRIBUTE_API_KEY", ""),
    tribute_webhook_secret=os.getenv("TRIBUTE_API_KEY", ""),
    admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
    db_path=os.getenv("DB_PATH", "data/bot.db"),
    port=int(os.getenv("PORT", "8080")),
)
