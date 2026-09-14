import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "8080"))
_DOMAIN = os.getenv("DOMAIN", "").strip()
if _DOMAIN and not _DOMAIN.startswith("http"):
    _DOMAIN = f"https://{_DOMAIN}"


@dataclass(frozen=True)
class Config:
    bot_token: str
    channel_id: int
    public_base_url: str
    crypto_token: str
    crypto_asset: str
    crypto_price: str
    crypto_currency_type: str
    tribute_api_key: str
    tribute_webhook_secret: str
    admin_ids: tuple[int, ...]
    db_path: str
    port: int
    use_webhook: bool


def _ids(raw: str) -> tuple[int, ...]:
    return tuple(int(x.strip()) for x in raw.split(",") if x.strip())


config = Config(
    bot_token=os.environ["BOT_TOKEN"],
    channel_id=int(os.environ["CHANNEL_ID"]),
    public_base_url=(
        os.getenv("PUBLIC_BASE_URL", "").rstrip("/") or _DOMAIN
    ),
    crypto_token=os.environ["CRYPTO_PAY_TOKEN"],
    crypto_asset=os.getenv("CRYPTO_ASSET", "USDT"),
    crypto_price=os.getenv("CRYPTO_PRICE", "5"),
    crypto_currency_type=os.getenv("CRYPTO_CURRENCY_TYPE", "crypto"),
    tribute_api_key=os.getenv("TRIBUTE_API_KEY", ""),
    tribute_webhook_secret=os.getenv("TRIBUTE_API_KEY", ""),
    admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
    db_path=os.getenv("DB_PATH", "/app/data/bot.db"),
    port=PORT,
    use_webhook=os.getenv("USE_WEBHOOK", "1") == "1",
)
