from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def sub_keyboard(month_price: str, asset: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💎 {month_price} {asset} — 30 дней",
                              callback_data="buy:30")],
        [InlineKeyboardButton(text="🔥 Выгоднее: 90 дней (−20%)",
                              callback_data="buy:90")],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="status")],
    ])


def pay_keyboard(pay_url: str, invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Я оплатил", callback_data=f"check:{invoice_id}")],
    ])


def tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад к тарифам", callback_data="start")],
    ])
