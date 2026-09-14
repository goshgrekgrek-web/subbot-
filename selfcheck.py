import os
os.environ.setdefault("BOT_TOKEN", "x")
os.environ.setdefault("CHANNEL_ID", "-100")
os.environ.setdefault("CRYPTO_PAY_TOKEN", "y")
os.environ.setdefault("PUBLIC_BASE_URL", "https://example.com")

import app.cryptobot as cb
import app.tribute as t
import app.keyboards
import app.state
import app.db as d

print("imports OK")
print("bad signature rejected:", not cb.verify_webhook(b"{}", "deadbeef"))

# корректная подпись CryptoPay
import hashlib, hmac, json
body = json.dumps({"update_type": "invoice_paid"}).encode()
secret = hashlib.sha256(b"y").digest()
sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
print("good signature accepted:", cb.verify_webhook(body, sig))

print("tribute parse:", t.parse_subscription_event(
    {"type": "regular", "subscription": {"telegram_user_id": 42, "id": "S1", "period_days": 30}}))

# схема БД создаётся без ошибок
import asyncio
asyncio.run(d.init_db())
print("db schema OK")
