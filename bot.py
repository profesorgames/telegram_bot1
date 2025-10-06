# -*- coding: utf-8 -*-
"""
Telegram-бот «Приём заказов» (aiogram 3.x)

Что умеет:
- Любой пользователь присылает текст — это заказ.
- Бот отправляет заказ администратору с инлайн-кнопками:
    • «Принять в работу» -> уведомляет заказчика: «Ваш заказ принят в работу ✅»
    • «Выполнено»        -> уведомляет заказчика: «Ваш заказ выполнен 🎉 Спасибо за обращение!»
- Логирует все заказы в orders.txt (имя, ID, текст).
- Жать кнопки может только администратор.
- После «Выполнено» заказ закрывается (кнопки исчезают).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
import html as py_html
import os

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties   # <-- нужно для parse_mode в 3.7+
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================== НАСТРОЙКИ ==================
# Вариант 1: просто вставь значения здесь:
BOT_TOKEN = os.getenv("BOT_TOKEN", "8383740107:AAHOcdULmxFo5a5YtL4-aJ6tvjbnT5SiVI8")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "1145467601"))  # ← замени на свой числовой ID

# (Если деплоишь на Render, удобнее задать BOT_TOKEN и ADMIN_ID в Environment Variables)
# ===============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

router = Router()

# ===== Модель и хранилище заказов =====
@dataclass
class Order:
    order_id: str
    user_id: int
    user_name: str
    text: str
    status: str  # 'new' | 'in_progress' | 'done'
    admin_msg_id: int | None = None

ORDERS: dict[str, Order] = {}


# ===== Утилиты =====
def display_name(user: types.User) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    if not name and user.username:
        name = f"@{user.username}"
    return name or f"id{user.id}"

def status_label(status: str) -> tuple[str, str]:
    match status:
        case "new":
            return "🆕", "Новый"
        case "in_progress":
            return "⏳", "В работе"
        case "done":
            return "✅", "Закрыт"
        case _:
            return "❔", "Неизвестно"

def admin_order_text(o: Order) -> str:
    icon, label = status_label(o.status)
    safe_text = py_html.escape(o.text)
    return (
        f"<b>Заказ #{o.order_id}</b>\n"
        f"👤 От: <code>{py_html.escape(o.user_name)}</code> (ID: <code>{o.user_id}</code>)\n"
        f"💬 Текст: <i>{safe_text}</i>\n"
        f"📌 Статус: {icon} <b>{label}</b>"
    )

def kb_new(order_id: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять в работу", callback_data=f"accept:{order_id}")
    kb.adjust(1)
    return kb.as_markup()

def kb_in_progress(order_id: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="⏳ В работе", callback_data="noop")
    kb.button(text="🏁 Выполнено", callback_data=f"done:{order_id}")
    kb.adjust(2)
    return kb.as_markup()

def log_order_created(o: Order):
    line = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{o.user_name} (ID: {o.user_id}) — \"{o.text}\"\n"
    )
    with open("orders.txt", "a", encoding="utf-8") as f:
        f.write(line)


# ===== Хендлеры =====
@router.message(CommandStart())
async def on_start(message: Message):
    await message.answer(
        "Привет! 👋\n"
        "Отправьте мне текст вашего заказа — например: <b>«Хочу заказать чтоб ачуну ебало начистили»</b>.\n\n"
        "Я передам запрос администратору и сообщу о статусе. 📨",
        parse_mode="HTML",
    )

@router.message(F.text)  # принимаем только текст как заказы
async def on_order(message: Message, bot: Bot):
    o = Order(
        order_id=str(uuid.uuid4())[:8],
        user_id=message.from_user.id,
        user_name=display_name(message.from_user),
        text=message.text.strip(),
        status="new"
    )
    ORDERS[o.order_id] = o

    # логирование
    try:
        log_order_created(o)
    except Exception as e:
        logging.exception("Не удалось записать в orders.txt: %s", e)

    # подтверждение пользователю
    await message.answer(
        "Спасибо! 🙌 Ваш заказ отправлен администратору.\n"
        "Сообщу, когда его примут в работу. 📨"
    )

    # сообщение администратору
    admin_msg = await bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_order_text(o),
        parse_mode="HTML",
        reply_markup=kb_new(o.order_id)
    )
    o.admin_msg_id = admin_msg.message_id
    logging.info("Новый заказ %s от %s (%s)", o.order_id, o.user_name, o.user_id)

@router.message(~F.text)  # не-текстовые сообщения
async def on_non_text(message: Message):
    await message.answer(
        "Пожалуйста, отправьте текст заказа 📝\n"
        "Например: <b>«Хочу заказать визитки»</b>.",
        parse_mode="HTML"
    )

# ----- Кнопки (только админ) -----
@router.callback_query(F.data.startswith("accept:"))
async def on_accept(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Эта кнопка доступна только администратору.", show_alert=True)
        return

    order_id = call.data.split(":", 1)[1]
    o = ORDERS.get(order_id)
    if not o:
        await call.answer("Этот заказ не найден или устарел.", show_alert=True)
        return
    if o.status == "done":
        await call.answer("Заказ уже закрыт.", show_alert=True)
        return
    if o.status == "in_progress":
        await call.answer("Уже в работе.", show_alert=False)
        return

    o.status = "in_progress"

    try:
        await call.message.edit_text(
            admin_order_text(o),
            parse_mode="HTML",
            reply_markup=kb_in_progress(o.order_id)
        )
    except Exception:
        pass

    try:
        await bot.send_message(
            chat_id=o.user_id,
            text="Ваш заказ принят в работу ✅\nМы приступили к выполнению!"
        )
    except Exception as e:
        logging.exception("Не удалось уведомить пользователя %s: %s", o.user_id, e)

    await call.answer("Заказ принят в работу.")

@router.callback_query(F.data.startswith("done:"))
async def on_done(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Эта кнопка доступна только администратору.", show_alert=True)
        return

    order_id = call.data.split(":", 1)[1]
    o = ORDERS.get(order_id)
    if not o:
        await call.answer("Этот заказ не найден или устарел.", show_alert=True)
        return
    if o.status == "done":
        await call.answer("Уже закрыт.", show_alert=False)
        return
    if o.status != "in_progress":
        await call.answer("Сначала примите заказ в работу.", show_alert=True)
        return

    o.status = "done"

    try:
        await call.message.edit_text(
            admin_order_text(o),
            parse_mode="HTML",
            reply_markup=None  # убрать клавиатуру — больше не нажать
        )
    except Exception:
        pass

    try:
        await bot.send_message(
            chat_id=o.user_id,
            text="Ваш заказ выполнен 🎉 Спасибо за обращение!"
        )
    except Exception as e:
        logging.exception("Не удалось уведомить пользователя %s: %s", o.user_id, e)

    await call.answer("Заказ закрыт. Готово! ✅")

@router.callback_query(F.data == "noop")
async def on_noop(call: CallbackQuery):
    await call.answer("Это индикатор статуса.", show_alert=False)


# ===== Точка входа =====
async def main():
    if BOT_TOKEN == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logging.warning("Вы не указали BOT_TOKEN! Вставьте токен в переменную BOT_TOKEN "
                        "или задайте переменную окружения BOT_TOKEN.")

    # ВАЖНО: для aiogram 3.7+ parse_mode задаётся через default=DefaultBotProperties(...)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("Бот запущен. Ожидаю сообщения…")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception("Критическая ошибка в polling: %s", e)

if __name__ == "__main__":
    asyncio.run(main())
