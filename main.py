import asyncio
import logging
import os
import sqlite3

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai_assistant import analyze_legal_case
from database import (
    init_db, 
    add_user, 
    create_appointment, 
    set_day_status, 
    archive_old_appointments,
    update_appointment_status
)
from keyboards import (
    get_main_reply_keyboard,
    get_specialists_inline_keyboard,
    get_time_slots_keyboard,
    get_phone_keyboard,
    get_admin_appointment_keyboard,
    get_client_reschedule_keyboard,
    generate_calendar_keyboard,
    generate_admin_day_menu,
    get_admin_main_keyboard
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Конфігурація адміністраторів та фахівців
ADMIN_NESSS = 5279915876
ADMIN_DENIS = 193003783
ADMIN_VLAD = 537795690

# Маршрутизація сповіщень: фахівець + супер-адмін Nesss
SPECIALIST_ADMIN_ROUTING = {
    "Адвокат Денис 👨‍⚖️": [ADMIN_DENIS, ADMIN_NESSS],
    "Адвокат Влад 👨‍⚖️": [ADMIN_VLAD, ADMIN_NESSS]
}

# Список для доступу до адмін-функцій та календаря
ADMIN_IDS = [ADMIN_NESSS, ADMIN_DENIS, ADMIN_VLAD]

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Планувальник нічного архівування старих записів
scheduler = AsyncIOScheduler()
scheduler.add_job(archive_old_appointments, 'cron', hour=3, minute=0)


# ==========================================
# 📋 FSM СТАТУСИ (МАШИНА СТАНІВ)
# ==========================================
class BookingState(StatesGroup):
    waiting_for_fio = State()
    waiting_for_phone = State()
    waiting_for_issue = State()
    choosing_specialist = State()
    waiting_for_date = State()
    choosing_time = State()
    admin_choosing_date = State()
    admin_choosing_time = State()


# ==========================================
# 🚀 КОМАНДА /START
# ==========================================
@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""

    add_user(telegram_id=user_id, full_name=first_name)

    greeting = f"Вітаю, {first_name}!" if (first_name.strip() and first_name != ".") else "Вітаю!"

    await message.answer(
        f"{greeting}\n\n"
        "Ви звернулися до сервісу запису на юридичну консультацію.\n"
        "Оберіть потрібний розділ у меню нижче:",
        reply_markup=get_main_reply_keyboard()
    )


# ==========================================
# 📝 СЦЕНАРІЙ ПОКРОКОВОГО ЗАПИСУ КЛІЄНТА
# ==========================================

@dp.message(F.text == "📅 Записатися на прийом")
async def start_booking(message: Message, state: FSMContext):
    await state.set_state(BookingState.waiting_for_fio)
    await message.answer("Будь ласка, вкажіть ваше **Прізвище, Ім'я та По батькові (ПІБ)**:", parse_mode="Markdown")


@dp.message(BookingState.waiting_for_fio)
async def process_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await state.set_state(BookingState.waiting_for_phone)
    await message.answer(
        "Дякую! Тепер вкажіть ваш **номер телефону** для зв'язку (можна скористатись кнопкою нижче):",
        reply_markup=get_phone_keyboard(),
        parse_mode="Markdown"
    )


@dp.message(BookingState.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)
    
    await state.set_state(BookingState.waiting_for_issue)
    await message.answer(
        "Дякую! Коротко опишіть суть вашого питання/проблеми:",
        reply_markup=types.ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )


@dp.message(BookingState.waiting_for_issue)
async def process_issue(message: types.Message, state: FSMContext):
    await state.update_data(issue=message.text)
    await state.set_state(BookingState.choosing_specialist)

    await message.answer(
        "Оберіть фахівця, до якого бажаєте записатися:",
        reply_markup=get_specialists_inline_keyboard()
    )


@dp.callback_query(F.data.startswith("select_spec_"), BookingState.choosing_specialist)
async def process_specialist_choice(callback: types.CallbackQuery, state: FSMContext):
    spec_code = callback.data.split("_")[2]
    specialist_name = "Адвокат Денис 👨‍⚖️" if spec_code == "denis" else "Адвокат Влад 👨‍⚖️"

    await state.update_data(specialist=specialist_name)
    await state.set_state(BookingState.waiting_for_date)

    legend_text = (
        f"Ви обрали: **{specialist_name}**\n\n"
        "📅 **Оберіть зручний день для консультації:**\n\n"
        "🟢 — Є вільні місця для запису\n"
        "🟡 — Залишилося мало слотів\n"
        "🔴 — День повністю зайнятий або вихідний\n\n"
        "_Натисніть на зелений або жовтий день, щоб обрати час._"
    )

    await callback.message.edit_text(
        legend_text,
        reply_markup=generate_calendar_keyboard(is_admin=False, specialist=specialist_name),
        parse_mode="Markdown"
    )
    try:
        await callback.answer()
    except Exception:
        pass


# ==========================================
# 🗓 ОБРОБКА КЛІЄНТСЬКОГО КАЛЕНДАРЯ
# ==========================================

@dp.callback_query(F.data.startswith("user_cal:"))
async def process_user_cal_nav(callback: CallbackQuery, state: FSMContext):
    _, year, month = callback.data.split(":")
    user_data = await state.get_data()
    specialist_name = user_data.get("specialist")

    await callback.message.edit_reply_markup(
        reply_markup=generate_calendar_keyboard(
            year=int(year), 
            month=int(month), 
            is_admin=False, 
            specialist=specialist_name
        )
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("user_date:"), BookingState.waiting_for_date)
async def process_user_date_selection(callback: types.CallbackQuery, state: FSMContext):
    date_str_raw = callback.data.split(":")[1]
    parts = date_str_raw.split("-")
    formatted_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str_raw

    user_data = await state.get_data()
    specialist_name = user_data.get("specialist")

    await state.update_data(date=formatted_date)
    await state.set_state(BookingState.choosing_time)

    await callback.message.edit_text(
        f"📅 Вибрано дату: **{formatted_date}**\n\nТепер оберіть зручний час для візиту:",
        reply_markup=get_time_slots_keyboard(date_str=formatted_date, specialist=specialist_name),
        parse_mode="Markdown"
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("time_"), BookingState.choosing_time)
async def process_time_choice(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass

    appointment_id = None
    try:
        selected_time = callback.data.split("_")[1]
        user_data = await state.get_data()
        user_id = callback.from_user.id

        fio = user_data.get('fio', 'Не вказано')
        phone = str(user_data.get('phone', 'Не вказано'))
        issue = user_data.get('issue', 'Не вказано')
        specialist = user_data.get('specialist', 'Адвокат Денис 👨‍⚖️')
        date_str = user_data.get('date', 'Не вказано')
        username = callback.from_user.username or "немає"

        # 1. Збереження запису в БД
        try:
            appointment_id = create_appointment(
                user_id=user_id,
                client_fio=fio,
                phone_number=phone,
                issue_description=issue,
                specialist=specialist,
                date_str=date_str,
                time_str=selected_time
            )
        except Exception as db_err:
            logging.error(f"Помилка запису в БД: {db_err}")

        # 2. Повідомлення клієнту
        confirmation_text = (
            "📩 **Запит на консультацію успішно надіслано!**\n\n"
            "Вашу заявку передано фахівцю. Очікуйте на підтвердження або дзвінок для уточнення деталей.\n\n"
            "📋 **Деталі вашої заявки:**\n"
            f"👤 **ПІБ:** {fio}\n"
            f"📱 **Телефон:** {phone}\n"
            f"📝 **Питання:** {issue}\n"
            f"⚖️ **Фахівець:** {specialist}\n"
            f"📅 **Дата та час:** {date_str} о {selected_time}"
        )
        await callback.message.edit_text(confirmation_text, parse_mode="Markdown")
        await callback.message.answer(
            "Ви можете скористатися меню нижче для навігації:",
            reply_markup=get_main_reply_keyboard()
        )

        # 3. ШІ аналіз справи
        try:
            ai_legal_analysis = await analyze_legal_case(issue)
        except Exception as ai_err:
            ai_legal_analysis = f"Не вдалося виконати аналіз: {ai_err}"

        # 4. Текст сповіщення
        admin_text = (
            "🔔 НОВИЙ ЗАПИС НА КОНСУЛЬТАЦІЮ!\n\n"
            f"👤 Клієнт (ПІБ): {fio}\n"
            f"📱 Телефон: {phone}\n"
            f"📝 Суть питання: {issue}\n"
            f"⚖️ До кого запис: {specialist}\n"
            f"📅 Дата та час: {date_str} о {selected_time}\n"
            f"💬 Telegram: @{username}\n\n"
            "-----------------------------------\n"
            "🤖 ЕКСПРЕС-АНАЛІЗ СПРАВИ (AI):\n\n"
            f"{ai_legal_analysis}"
        )

        app_id = appointment_id if appointment_id else 0

        # 5. Адресне надсилання відповідному адвокату + копія Nesss
        recipients = SPECIALIST_ADMIN_ROUTING.get(specialist, ADMIN_IDS)
        for admin_id in recipients:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=admin_text,
                    reply_markup=get_admin_appointment_keyboard(appointment_id=app_id, user_id=user_id)
                )
            except Exception as admin_err:
                logging.error(f"Помилка відправки адміну {admin_id}: {admin_err}")

        await state.clear()

    except Exception as general_err:
        logging.error(f"Критична помилка у process_time_choice: {general_err}")
        await callback.message.answer("Виникла помилка під час збереження запису. Спробуйте ще раз.")


# ==========================================
# ⚙️ ОБРОБКА ДІЙ АДМІНІСТРАТОРА
# ==========================================

@dp.callback_query(F.data.startswith("app_approve_"))
async def approve_appointment(callback: types.CallbackQuery):
    try:
        await callback.answer("Обробка...")
    except Exception:
        pass

    data_parts = callback.data.split("_")
    app_id = int(data_parts[2])
    client_user_id = int(data_parts[3])

    # 1. Оновлюємо статус у базі даних
    update_appointment_status(appointment_id=app_id, new_status="CONFIRMED")

    # 2. Змінюємо текст картки і прибираємо кнопки
    updated_text = (callback.message.text or "") + "\n\n🟢 СТАТУС: ПІДТВЕРДЖЕНО"
    try:
        await callback.message.edit_text(updated_text, reply_markup=None)
    except Exception:
        pass

    # 3. Сповіщаємо клієнта
    try:
        await bot.send_message(
            chat_id=client_user_id,
            text="🎉 **Ваш запис на консультацію підтверджено!**\n\nФахівець чекає на вас у обраний час.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не вдалося сповістити клієнта {client_user_id}: {e}")


@dp.callback_query(F.data.startswith("app_reject_"))
async def reject_appointment(callback: types.CallbackQuery):
    try:
        await callback.answer("Обробка...")
    except Exception:
        pass

    data_parts = callback.data.split("_")
    app_id = int(data_parts[2])
    client_user_id = int(data_parts[3])

    # 1. Оновлюємо статус у базі даних
    update_appointment_status(appointment_id=app_id, new_status="CANCELLED")

    # 2. Змінюємо текст картки і прибираємо кнопки
    updated_text = (callback.message.text or "") + "\n\n🔴 СТАТУС: ВІДХИЛЕНО"
    try:
        await callback.message.edit_text(updated_text, reply_markup=None)
    except Exception:
        pass

    # 3. Сповіщаємо клієнта
    try:
        await bot.send_message(
            chat_id=client_user_id,
            text="❌ Перепрошую, наші працівники зайняті і в цей час не зможуть прийняти вас. Спробуйте обрати інший час або зверніться пізніше.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не вдалося сповістити клієнта {client_user_id}: {e}")


@dp.callback_query(F.data.startswith("app_resched_"))
async def reschedule_appointment(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass

    client_user_id = int(callback.data.split("_")[-1])
    await state.update_data(reschedule_user_id=client_user_id)
    await state.set_state(BookingState.admin_choosing_date)

    await callback.message.reply(
        "Оберіть нову дату для клієнта:",
        reply_markup=generate_calendar_keyboard(is_admin=True)
    )


@dp.callback_query(F.data.startswith("admin_date:"), BookingState.admin_choosing_date)
async def process_admin_reschedule_date(callback: types.CallbackQuery, state: FSMContext):
    date_str_raw = callback.data.split(":")[1]
    parts = date_str_raw.split("-")
    formatted_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str_raw

    await state.update_data(reschedule_date=formatted_date)
    await state.set_state(BookingState.admin_choosing_time)

    await callback.message.edit_text(
        f"📅 Вибрано нову дату: **{formatted_date}**\n\nТепер оберіть новий час для клієнта:",
        reply_markup=get_time_slots_keyboard(date_str=formatted_date),
        parse_mode="Markdown"
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("time_"), BookingState.admin_choosing_time)
async def process_admin_time_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer("Пропозицію надіслано клієнту!")
    except Exception:
        pass

    new_time = callback.data.split("_")[1]
    admin_data = await state.get_data()
    
    client_user_id = admin_data.get("reschedule_user_id")
    new_date = admin_data.get("reschedule_date")
    admin_id = callback.from_user.id

    await callback.message.edit_text(
        f"⏳ Клієнту надіслано пропозицію нового часу:\n📅 **{new_date}** о **{new_time}**",
        parse_mode="Markdown"
    )

    try:
        reschedule_text = (
            "🗓 **Вам запропоновано інший час для консультації!**\n\n"
            f"Адвокат пропонує перенести візит на:\n"
            f"📅 **Дата:** {new_date}\n"
            f"⏰ **Час:** {new_time}\n\n"
            "Будь ласка, оберіть дію нижче:"
        )
        await bot.send_message(
            chat_id=client_user_id,
            text=reschedule_text,
            reply_markup=get_client_reschedule_keyboard(admin_id=admin_id),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не вдалося надіслати новий час клієнту {client_user_id}: {e}")

    await state.clear()


# ==========================================
# 📩 ВІДПОВІДІ КЛІЄНТА НА ПЕРЕНЕСЕННЯ
# ==========================================

@dp.callback_query(F.data.startswith("client_accept_resched_"))
async def client_accept_reschedule(callback: types.CallbackQuery):
    try:
        await callback.answer("Час підтверджено!")
    except Exception:
        pass

    admin_id = int(callback.data.split("_")[-1])
    client_name = callback.from_user.full_name
    username = f"@{callback.from_user.username}" if callback.from_user.username else "немає"
    clean_text = (callback.message.text or "").replace("Будь ласка, оберіть дію нижче:", "").strip()

    await callback.message.edit_text(
        "🎉 **Дякуємо! Новий час консультації успішно підтверджено.**\n\n"
        "Чекаємо на вас у визначений час!",
        parse_mode="Markdown"
    )

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                "✅ **КЛІЄНТ ПІДТВЕРДИВ НОВИЙ ЧАС!**\n\n"
                f"👤 **Клієнт:** {client_name} ({username})\n\n"
                f"📋 **Узгоджені деталі:**\n{clean_text}"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не вдалося сповістити адміна {admin_id}: {e}")


@dp.callback_query(F.data.startswith("client_decline_resched_"))
async def client_decline_reschedule(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass

    admin_id = int(callback.data.split("_")[-1])
    client_name = callback.from_user.full_name
    username = f"@{callback.from_user.username}" if callback.from_user.username else "немає"

    decline_text = (
        "😔 **На жаль, нам не вдалося погодити час консультації в чат-боті.**\n\n"
        "Ви завжди можете зв'язатися з нами особисто або переглянути прямі номери у розділі **«📞 Контакти»** в головному меню."
    )
    await callback.message.edit_text(decline_text, parse_mode="Markdown")

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                "🔴 **Клієнт відхилив запропонований час.**\n\n"
                f"👤 **Клієнт:** {client_name} ({username})"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не вдалося сповістити адміна {admin_id}: {e}")


# ==========================================
# 🚦 АДМІН-КАЛЕНДАР
# ==========================================

@dp.message(Command("admin_calendar"))
@dp.message(F.text == "⚙️ Календар зайнятості")
async def show_admin_calendar_text(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "⚙️ **Управління завантаженістю днів (Світлофор)**\n\n"
        "Натисніть на день, щоб змінити його статус (Заблокувати 🔴 / Відкрити 🟢 / Авто ⚙️):",
        reply_markup=generate_calendar_keyboard(is_admin=True),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("admin_date:"))
async def process_admin_date(callback: CallbackQuery):
    date_str = callback.data.split(":")[1]
    await callback.message.edit_text(
        f"📅 **Налаштування дня {date_str}**\n\nОберіть потрібну дію:",
        reply_markup=generate_admin_day_menu(date_str),
        parse_mode="Markdown"
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("set_status:"))
async def process_set_day_status(callback: CallbackQuery):
    _, date_str, new_status = callback.data.split(":")
    set_day_status(date_str, new_status)

    status_labels = {"red": "🔴 Заблоковано", "green": "🟢 Відкрито", "auto": "⚙️ Автоматичний режим"}
    try:
        await callback.answer(f"Статус {date_str} змінено на: {status_labels.get(new_status)}")
    except Exception:
        pass

    await callback.message.edit_text(
        "⚙️ **Управління завантаженістю днів (Оновлено)**:\n\nОберіть день для налаштування:",
        reply_markup=generate_calendar_keyboard(is_admin=True),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("admin_cal:"))
async def process_admin_cal_nav(callback: CallbackQuery):
    _, year, month = callback.data.split(":")
    await callback.message.edit_reply_markup(
        reply_markup=generate_calendar_keyboard(year=int(year), month=int(month), is_admin=True)
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data == "back_to_admin_cal")
async def process_back_to_admin_cal(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ **Управління завантаженістю днів (Світлофор)**:",
        reply_markup=generate_calendar_keyboard(is_admin=True),
        parse_mode="Markdown"
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("view_apps:"))
async def process_view_appointments(callback: CallbackQuery):
    date_str_raw = callback.data.split(":")[1]
    try:
        parts = date_str_raw.split("-")
        date_formatted = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str_raw
    except Exception:
        date_formatted = date_str_raw

    with sqlite3.connect("bot_database.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT client_fio, phone_number, appointment_time, issue_description, specialist 
            FROM appointments 
            WHERE (appointment_date = ? OR appointment_date = ?) AND status != 'CANCELLED'
            ORDER BY appointment_time ASC
        """, (date_str_raw, date_formatted))
        apps = cursor.fetchall()

    if not apps:
        try:
            await callback.answer(f"ℹ️ На {date_formatted} записи відсутні.", show_alert=True)
        except Exception:
            pass
        return

    text = f"📋 **Записи на {date_formatted}:**\n\n"
    for app in apps:
        fio, phone, time_str, issue, spec = app
        text += f"⏰ **{time_str}** — {fio} ({spec})\n📞 {phone}\n💬 _{issue or 'Без опису'}_\n\n"

    await callback.message.edit_text(
        text,
        reply_markup=generate_admin_day_menu(date_str_raw),
        parse_mode="Markdown"
    )
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data == "close_calendar")
async def process_close_calendar(callback: CallbackQuery):
    await callback.message.delete()
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(F.data == "ignore")
async def process_ignore(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass


# ==========================================
# ℹ️ ІНФОРМАЦІЙНІ РОЗДІЛИ ТА МОЇ ЗАПИСИ
# ==========================================

@dp.message(F.text == "ℹ️ Про нас")
async def about_cmd(message: types.Message):
    await message.answer(
        "⚖️ **Юридична консультація:**\n\n"
        "Цивільне, сімейне, господарське, кримінальне право, представництво інтересів фізичних та юридичних осіб у судах і державних органах.\n"
        "📍 Прийом здійснюється за попереднім записом.",
        parse_mode="Markdown"
    )


@dp.message(F.text == "📞 Контакти")
async def contacts_cmd(message: types.Message):
    await message.answer(
        "📞 **Контактна інформація**\n\n"
        "📱 **Телефон Адвоката Дениса:** +380 95 565 9399\n"
        "📱 **Телефон Адвоката Влада:** +380 50 237 1782\n"
        "⏰ **Графік роботи:** Пн-Пт 09:00 - 18:00",
        parse_mode="Markdown"
    )


@dp.message(F.text == "📋 Мої записи")
async def show_user_appointments(message: Message):
    user_id = message.from_user.id
    
    with sqlite3.connect("bot_database.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT appointment_date, appointment_time, specialist, issue_description, status
            FROM appointments
            WHERE user_id = ? AND status != 'CANCELLED'
            ORDER BY appointment_date ASC, appointment_time ASC
        """, (user_id,))
        apps = cursor.fetchall()
        
    if not apps:
        await message.answer("ℹ️ У вас немає активних записів на консультацію.")
        return

    text = "📋 **Ваші заплановані консультації:**\n\n"
    for app in apps:
        date_str, time_str, spec, issue, status = app
        text += f"📅 **Дата:** {date_str} о {time_str}\n"
        text += f"👨‍⚖️ **Спеціаліст:** {spec or 'Адвокат'}\n"
        text += f"💬 **Питання:** _{issue or 'Не вказано'}_\n"
        text += f"📌 **Статус:** {status}\n"
        text += "-----------------------------------\n"
        
    await message.answer(text, parse_mode="Markdown")


# ==========================================
# 👨‍⚖️ ВХІД В АДМІН-ПАНЕЛЬ
# ==========================================

@dp.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            "👨‍⚖️ **Ласкаво просимо до адмін-панелі!**\n\n"
            "Використовуйте меню нижче для керування графіком та перегляду записів:",
            reply_markup=get_admin_main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ У вас немає прав доступу до адмін-панелі.")


# ==========================================
# 🚀 ЗАПУСК
# ==========================================
async def main():
    init_db()
    scheduler.start()
    print("--- БОТ УСПІШНО ЗАПУЩЕНИЙ! ---")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())