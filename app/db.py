import aiosqlite
import time
from contextlib import asynccontextmanager
from app.config import config

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    username   TEXT,
    created_at INTEGER NOT NULL
);

-- один активный доступ = одна строка
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id        INTEGER NOT NULL,
    source       TEXT NOT NULL,           -- 'cryptobot' | 'tribute'
    external_id  TEXT,                    -- id инвойса CryptoBot / подписки Tribute
    plan_days    INTEGER NOT NULL,
    started_at   INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    status       TEXT NOT NULL,           -- 'active' | 'expired' | 'revoked'
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_user   ON subscriptions(tg_id, status);
CREATE INDEX IF NOT EXISTS idx_sub_expiry ON subscriptions(status, expires_at);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    provider     TEXT NOT NULL,           -- 'cryptobot' | 'tribute'
    external_id  TEXT NOT NULL,
    tg_id        INTEGER,
    amount       TEXT,
    asset        TEXT,
    status       TEXT NOT NULL,           -- 'pending' | 'paid' | 'failed'
    created_at   INTEGER NOT NULL,
    paid_at      INTEGER,
    UNIQUE(provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(tg_id, created_at DESC);

-- идемпотентность вебхуков: повтор не должен выдать вторую подписку
CREATE TABLE IF NOT EXISTS processed_events (
    provider    TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (provider, event_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor      TEXT,
    action     TEXT NOT NULL,
    tg_id      INTEGER,
    details    TEXT,
    created_at INTEGER NOT NULL
);
"""


def now() -> int:
    return int(time.time())


@asynccontextmanager
async def conn():
    db = await aiosqlite.connect(config.db_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    import os
    os.makedirs(os.path.dirname(config.db_path) or ".", exist_ok=True)
    async with conn() as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def upsert_user(tg_id: int, username: str | None) -> None:
    async with conn() as db:
        await db.execute(
            "INSERT INTO users(tg_id, username, created_at) VALUES(?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
            (tg_id, username, now()),
        )
        await db.commit()


async def claim_event(provider: str, event_id: str) -> bool:
    """True — событие новое, обрабатываем. False — уже видели."""
    async with conn() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO processed_events(provider, event_id, created_at) VALUES(?,?,?)",
            (provider, str(event_id), now()),
        )
        await db.commit()
        return cur.rowcount > 0


async def audit(actor: str, action: str, tg_id: int | None = None, details: str = "") -> None:
    async with conn() as db:
        await db.execute(
            "INSERT INTO audit_log(actor, action, tg_id, details, created_at) VALUES(?,?,?,?,?)",
            (actor, action, tg_id, details, now()),
        )
        await db.commit()


async def active_subscription(tg_id: int, source: str | None = None):
    q = ("SELECT * FROM subscriptions WHERE tg_id=? AND status='active' AND expires_at>?"
         + (" AND source=?" if source else "") + " ORDER BY expires_at DESC LIMIT 1")
    args = (tg_id, now()) + ((source,) if source else ())
    async with conn() as db:
        cur = await db.execute(q, args)
        return await cur.fetchone()


async def add_subscription(tg_id: int, source: str, external_id: str,
                           plan_days: int) -> int:
    """Продлевает активную подписку того же источника, иначе создаёт новую."""
    t = now()
    existing = await active_subscription(tg_id, source)
    async with conn() as db:
        if existing:
            new_expiry = existing["expires_at"] + plan_days * 86400
            await db.execute(
                "UPDATE subscriptions SET expires_at=?, external_id=? WHERE id=?",
                (new_expiry, external_id, existing["id"]),
            )
            await db.commit()
            return new_expiry
        expiry = t + plan_days * 86400
        await db.execute(
            "INSERT INTO subscriptions(tg_id, source, external_id, plan_days,"
            " started_at, expires_at, status, created_at) VALUES(?,?,?,?,?,?,'active',?)",
            (tg_id, source, external_id, plan_days, t, expiry, t),
        )
        await db.commit()
        return expiry


async def cancel_subscription(tg_id: int, source: str) -> bool:
    async with conn() as db:
        cur = await db.execute(
            "UPDATE subscriptions SET status='revoked' "
            "WHERE tg_id=? AND source=? AND status='active'",
            (tg_id, source),
        )
        await db.commit()
        return cur.rowcount > 0


async def expired_batch(limit: int = 100):
    async with conn() as db:
        cur = await db.execute(
            "SELECT * FROM subscriptions WHERE status='active' AND expires_at<=? LIMIT ?",
            (now(), limit),
        )
        return await cur.fetchall()


async def mark_expired(sub_id: int) -> None:
    async with conn() as db:
        await db.execute("UPDATE subscriptions SET status='expired' WHERE id=?", (sub_id,))
        await db.commit()


async def expiring_soon(min_sec: int, max_sec: int):
    """Кому напомнить: активные, истекающие в окне [min_sec, max_sec] от сейчас."""
    async with conn() as db:
        cur = await db.execute(
            "SELECT * FROM subscriptions WHERE status='active' AND expires_at BETWEEN ? AND ?",
            (now() + min_sec, now() + max_sec),
        )
        return await cur.fetchall()


async def save_payment(provider: str, external_id: str, tg_id: int | None,
                       amount: str, asset: str, status: str) -> None:
    t = now()
    async with conn() as db:
        await db.execute(
            "INSERT INTO payments(provider, external_id, tg_id, amount, asset, status,"
            " created_at, paid_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(provider, external_id) DO UPDATE SET status=excluded.status,"
            " paid_at=excluded.paid_at, tg_id=COALESCE(excluded.tg_id, payments.tg_id)",
            (provider, str(external_id), tg_id, str(amount), asset, status, t,
             t if status == "paid" else None),
        )
        await db.commit()


async def stats() -> dict:
    async with conn() as db:
        async def one(q, *a):
            cur = await db.execute(q, a)
            r = await cur.fetchone()
            return r[0] if r else 0
        return {
            "users": await one("SELECT COUNT(*) FROM users"),
            "active": await one(
                "SELECT COUNT(*) FROM subscriptions WHERE status='active' AND expires_at>?", now()),
            "paid": await one("SELECT COUNT(*) FROM payments WHERE status='paid'"),
            "ico": await one("SELECT COUNT(*) FROM payments WHERE status='paid' AND provider='cryptobot'"),
            "tribute": await one("SELECT COUNT(*) FROM payments WHERE status='paid' AND provider='tribute'"),
        }
