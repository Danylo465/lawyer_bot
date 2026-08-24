import calendar
import sqlite3
from datetime import datetime
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import get_day_color


# 1. ГОЛОВНЕ МЕНЮ КЛІЄНТА (Reply)
def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записатися на прийом")],
            [KeyboardButton(text="ℹ️ Про нас"), KeyboardButton(text="📞 Контакти")],
            [KeyboardButton(text="📋 Мої записи")]
        ],
        resize_keyboard=True
    )


# 2. ГОЛОВНЕ МЕНЮ АДМІНА (Reply)
def get_admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚙️ Календар зайнятості")],
            [KeyboardButton(text="📋 Мої записи"), KeyboardButton(text="ℹ️ Про нас")]
        ],
        resize_keyboard=True
    )


# 3. ВИБІР ФАХІВЦЯ (Inline)
def get_specialists_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍⚖️ Адвокат Денис", callback_data="select_spec_denis")],
            [InlineKeyboardButton(text="👨‍⚖️ Адвокат Влад", callback_data="select_spec_vlad")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="close_calendar")]
        ]
    )


# 4. ДИНАМІЧНИЙ ВИБІР ЧАСУ З БЛОКУВАННЯМ ЗАЙНЯТИХ СЛОТІВ (Inline)
def get_time_slots_keyboard(date_str: str = None, specialist: str = None) -> InlineKeyboardMarkup:
    all_times = ["09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00"]
    booked_times = []

    if date_str:
        try:
            parts = date_str.split("-")
            formatted_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str
        except Exception:
            formatted_date = date_str

        with sqlite3.connect("bot_database.db") as conn:
            cursor = conn.cursor()
            if specialist:
                cursor.execute("""
                    SELECT appointment_time FROM appointments 
                    WHERE (appointment_date = ? OR appointment_date = ?) 
                      AND specialist = ?
                      AND status != 'CANCELLED'
                """, (date_str, formatted_date, specialist))
            else:
                cursor.execute("""
                    SELECT appointment_time FROM appointments 
                    WHERE (appointment_date = ? OR appointment_date = ?) 
                      AND status != 'CANCELLED'
                """, (date_str, formatted_date))
            
            booked_times = [row[0] for row in cursor.fetchall()]

    buttons = []
    row = []

    for t in all_times:
        if t in booked_times:
            row.append(InlineKeyboardButton(text=f"❌ {t}", callback_data="ignore"))
        else:
            row.append(InlineKeyboardButton(text=t, callback_data=f"time_{t}"))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="close_calendar")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# 5. КНОПКА ВІДПРАВКИ ТЕЛЕФОНУ (Reply)
def get_phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися номером телефону", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# 6. КНОПКИ ДІЙ ДЛЯ АДМІНА (Inline)
def get_admin_appointment_keyboard(appointment_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Прийняти", callback_data=f"app_approve_{appointment_id}_{user_id}"),
            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"app_reject_{appointment_id}_{user_id}")
        ],
        [
            InlineKeyboardButton(text="📅 Запропонувати інший час", callback_data=f"app_resched_{appointment_id}_{user_id}")
        ]
    ])


# 7. КНОПКИ ДЛЯ КЛІЄНТА НА ПРОПОЗИЦІЮ ПЕРЕНЕСЕННЯ (Inline)
def get_client_reschedule_keyboard(admin_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Прийняти новий час", callback_data=f"client_accept_resched_{admin_id}"),
            InlineKeyboardButton(text="❌ Мені не підходить", callback_data=f"client_decline_resched_{admin_id}")
        ]
    ])


MONTH_NAMES = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
    5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
    9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"
}


# 8. ГЕНЕРАТОР КАЛЕНДАРЯ (Компактний кольоровий світлофор)
def generate_calendar_keyboard(year: int = None, month: int = None, is_admin: bool = False, specialist: str = None) -> InlineKeyboardMarkup:
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    builder = InlineKeyboardBuilder()

    month_title = f"{MONTH_NAMES[month]} {year}"
    builder.row(InlineKeyboardButton(text=month_title, callback_data="ignore"))

    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    builder.row(*[InlineKeyboardButton(text=day, callback_data="ignore") for day in week_days])

    month_calendar = calendar.monthcalendar(year, month)
    prefix = "admin_date" if is_admin else "user_date"

    COLOR_MAPPING = {
        "🟢": "🟩",
        "🟡": "🟨",
        "🔴": "🟥"
    }

    for week in month_calendar:
        row_buttons = []
        for weekday_idx, day in enumerate(week):
            if day == 0:
                row_buttons.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                color = get_day_color(date_str, specialist)
                
                # Субота (5) та Неділя (6) - вихідні
                is_weekend = weekday_idx in (5, 6)

                if is_weekend and not is_admin:
                    button_text = f"▪️{day}"
                    cb_data = "ignore"
                else:
                    badge = COLOR_MAPPING.get(color, "🟩")
                    button_text = f"{badge}{day}"

                    if not is_admin and color == "🔴":
                        cb_data = "ignore"
                    else:
                        cb_data = f"{prefix}:{date_str}"

                row_buttons.append(
                    InlineKeyboardButton(
                        text=button_text,
                        callback_data=cb_data
                    )
                )
        builder.row(*row_buttons)

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1

    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    nav_prefix = "admin_cal" if is_admin else "user_cal"

    builder.row(
        InlineKeyboardButton(text="◀️", callback_data=f"{nav_prefix}:{prev_year}:{prev_month}"),
        InlineKeyboardButton(text="❌ Закрити", callback_data="close_calendar"),
        InlineKeyboardButton(text="▶️", callback_data=f"{nav_prefix}:{next_year}:{next_month}")
    )

    return builder.as_markup()


# 9. МЕНЮ НАЛАШТУВАННЯ ДНЯ ДЛЯ АДМІНА
def generate_admin_day_menu(date_str: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="🟥 Заблокувати (Червоний)", callback_data=f"set_status:{date_str}:red")
    builder.button(text="🟩 Відкрити (Зелений)", callback_data=f"set_status:{date_str}:green")
    builder.button(text="⚙️ Автоматичний режим", callback_data=f"set_status:{date_str}:auto")
    builder.button(text="📋 Записи на цей день", callback_data=f"view_apps:{date_str}")
    builder.button(text="⬅️ Назад до календаря", callback_data="back_to_admin_cal")

    builder.adjust(1)
    return builder.as_markup()