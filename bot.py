# -*- coding: utf-8 -*-
"""
Telegram-бот «Приём заказов» на aiogram 3.x

Функции:
- Любой пользователь отправляет боту текст заказа.
- Бот пересылает заказ админу с кнопками:
    • «Принять в работу» -> заказчику: «Ваш заказ принят в работу ✅»
    • «Выполнено»        -> заказчику: «Ваш заказ выполнен 🎉 Спасибо за обращение!»
- Логирование заказов в orders.txt (имя, ID пользователя, текст).
- Защита кнопок: нажимать может только администратор.
- После выполнения заказ помечается как закрытый (кнопки больше не активны).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
import html as py_html  # для экранирования пользовательского текста

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ===================== НАСТРОЙКИ =====================
# 1) ВСТАВЬТЕ СВОЙ ТОКЕН БОТА:
BOT_TOKEN = "8383740107:AAHOcdULmxFo5a5YtL4-aJ6tvjbnT5SiVI8"

# 2) ВСТАВЬТЕ СВОЙ TELEGRAM ID (админ, кто получает заказы и жмёт кнопки):
ADMIN_ID = 1145467601  # ← замените на ваш числовой ID

# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

router = Router()

# ===== Модель и «хранилище» заказов (простая память процесса) =====
@dataclass
class Order:
    order_id: str
    user_id: int
    user_name: str
    text: str
    status: str  # 'new' | 'in_progress' | 'done'
    admin_msg_id: int | None = None

# По ключу order_id
ORDERS: dict[str, Order] = {}


# ===================== УТИЛИТЫ =====================

def display_name(user: types.User) -> str:
    """Читабельное имя отправителя для логов/админа."""
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    if not name and user.username:
        name = f"@{user.username}"
    return name or f"id{user.id}"

def status_label(status: str) -> tuple[str, str]:
    """Иконка и подпись статуса."""
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
    """Текст сообщения админу про заказ."""
    icon, label = status_label(o.status)
    # Экранируем пользовательский текст для HTML
    safe_text = py_html.escape(o.text)
    return (
        f"<b>Заказ #{o.order_id}</b>\n"
        f"👤 От: <code>{py_html.escape(o.user_name)}</code> (ID: <code>{o.user_id}</code>)\n"
        f"💬 Текст: <i>{safe_text}</i>\n"
        f"📌 Статус: {icon} <b>{label}</b>"
    )

def kb_new(order_id: str):
    """Клавиатура для нового заказа (только «Принять в работу»)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять в работу", callback_data=f"accept:{order_id}")
    kb.adjust(1)
    return kb.as_markup()

def kb_in_progress(order_id: str):
    """Клавиатура для статуса 'в работе'."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⏳ В работе", callback_data="noop")  # индикатор
    kb.button(text="🏁 Выполнено", callback_data=f"done:{order_id}")
    kb.adjust(2)
    return kb.as_markup()

# ===================== ЛОГИРОВАНИЕ =====================

def log_order_created(o: Order):
    """Записать заказ в файл orders.txt (имя, ID, текст)."""
    line = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{o.user_name} (ID: {o.user_id}) — \"{o.text}\"\n"
    )
    with open("orders.txt", "a", encoding="utf-8") as f:
        f.write(line)

# ===================== ХЕНДЛЕРЫ =====================

@router.message(CommandStart())
async def on_start(message: Message):
    await message.answer(
        "Привет! 👋\n"
        "Отправьте мне текст вашего заказа — например: <b>«Хочу заказать логотип»</b>.\n\n"
        "Я передам ваш запрос администратору и сообщу о статусе. 📨",
        parse_mode="HTML"
    )

@router.message(F.text)  # Принимаем только текст как заказы
async def on_order(message: Message, bot: Bot):
    # Создаём объект заказа
    o = Order(
        order_id=str(uuid.uuid4())[:8],  # компактный ID
        user_id=message.from_user.id,
        user_name=display_name(message.from_user),
        text=message.text.strip(),
        status="new"
    )
    ORDERS[o.order_id] = o

    # Логирование в файл
    try:
        log_order_created(o)
    except Exception as e:
        logging.exception("Не удалось записать в orders.txt: %s", e)

    # Сообщение пользователю-отправителю (подтверждение)
    await message.answer(
        "Спасибо! 🙌 Ваш заказ отправлен администратору.\n"
        "Я сообщу, когда его примут в работу. 📨"
    )

    # Сообщение администратору с инлайн-кнопками
    admin_msg = await bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_order_text(o),
        parse_mode="HTML",
        reply_markup=kb_new(o.order_id)
    )
    o.admin_msg_id = admin_msg.message_id
    logging.info("Новый заказ %s от %s (%s)", o.order_id, o.user_name, o.user_id)

@router.message(~F.text)  # Не-текстовые сообщения
async def on_non_text(message: Message):
    await message.answer(
        "Пожалуйста, отправьте текст заказа 📝\n"
        "Например: <b>«Хочу заказать визитки»</b>.",
        parse_mode="HTML"
    )

# -------- КНОПКИ (только админ) --------

@router.callback_query(F.data.startswith("accept:"))
async def on_accept(call: CallbackQuery, bot: Bot):
    # Только админ может нажимать
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
        await call.answer("Заказ уже принят в работу.", show_alert=False)
        return

    # Обновить статус
    o.status = "in_progress"

    # Обновить сообщение админа (текст + клавиатура)
    try:
        await call.message.edit_text(
            admin_order_text(o),
            parse_mode="HTML",
            reply_markup=kb_in_progress(o.order_id)
        )
    except Exception:
        # на случай если сообщение редактировать нельзя (редко)
        pass

    # Уведомить заказчика
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
    # Только админ
    if call.from_user.id != ADMIN_ID:
        await call.answer("Эта кнопка доступна только администратору.", show_alert=True)
        return

    order_id = call.data.split(":", 1)[1]
    o = ORDERS.get(order_id)
    if not o:
        await call.answer("Этот заказ не найден или устарел.", show_alert=True)
        return
    if o.status == "done":
        await call.answer("Заказ уже закрыт.", show_alert=False)
        return

    # Разрешаем завершить только из статуса «в работе»
    if o.status != "in_progress":
        await call.answer("Сначала примите заказ в работу.", show_alert=True)
        return

    # Закрываем заказ
    o.status = "done"

    # Обновляем сообщение админа: ставим «Закрыт» и УБИРАЕМ клавиатуру,
    # чтобы нельзя было нажать повторно.
    try:
        await call.message.edit_text(
            admin_order_text(o),
            parse_mode="HTML",
            reply_markup=None  # убрать инлайн-кнопки
        )
    except Exception:
        pass

    # Уведомляем заказчика
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
    # Безопасно реагируем на «индикаторные» кнопки
    await call.answer("Это индикатор статуса.", show_alert=False)


# ===================== ТОЧКА ВХОДА =====================

async def main():
    if BOT_TOKEN == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logging.warning("Вы не указали BOT_TOKEN! Вставьте токен в переменную BOT_TOKEN.")
    bot = Bot(BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("Бот запущен. Ожидаю сообщения…")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception("Критическая ошибка в polling: %s", e)

if __name__ == "__main__":
    asyncio.run(main())
