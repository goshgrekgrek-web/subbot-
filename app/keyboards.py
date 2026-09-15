from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def sub_keyboard(month_price: str | None = None, asset: str | None = None) -> InlineKeyboardMarkup:
    """Главное меню: сначала выбираем способ оплаты."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 CryptoBot — USDT", callback_data="paymethod:crypto")],
        [InlineKeyboardButton(text="💳 Tribute — карта / ₽", url="https://t.me/tribute/app?startapp=s16lb")],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="status")],
    ])


def crypto_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 1 месяц — 11 USDT", callback_data="buy:30")],
        [InlineKeyboardButton(text="🔥 3 месяца — 33 USDT", callback_data="buy:90")],
        [InlineKeyboardButton(text="👑 1 год — 133 USDT", callback_data="buy:365")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="start")],
    ])


def pay_keyboard(pay_url: str, invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Я оплатил", callback_data=f"check:{invoice_id}")],
        [InlineKeyboardButton(text="↩️ К способам оплаты", callback_data="start")],
    ])


def tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад к тарифам", callback_data="start")],
    ])
