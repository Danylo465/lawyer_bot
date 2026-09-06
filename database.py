import sqlite3
from datetime import datetime, timedelta

DB_NAME = "bot_database.db"


def init_db():
    """Створює всі необхідні таблиці."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # 1. Таблиця користувачів
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Таблиця записів
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                client_fio TEXT,
                phone_number TEXT,
                issue_description TEXT,
                specialist TEXT,
                appointment_date TEXT,
                appointment_time TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Таблиця для Світлофора (ручні статуси днів)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS day_settings (
                date TEXT PRIMARY KEY,
                status TEXT DEFAULT 'auto',
                note TEXT
            )
        """)

        conn.commit()
        print("✅ Базу даних та таблиці успішно оновлено!")


def update_appointment_status(appointment_id: int, new_status: str):
    """Оновлює статус конкретного запису."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE appointments
            SET status = ?
            WHERE id = ?
        """, (new_status, appointment_id))
        conn.commit()


def archive_old_appointments(days: int = 30):
    """Архівує записи, старші за вказану кількість днів."""
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    cutoff_date_dots = (datetime.now() - timedelta(days=days)).strftime("%d.%m.%Y")

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE appointments 
            SET status = 'ARCHIVED' 
            WHERE (appointment_date < ? OR appointment_date < ?)
              AND status != 'ARCHIVED'
        """, (cutoff_date, cutoff_date_dots))
        conn.commit()


def add_user(telegram_id: int, full_name: str, phone_number: str = None):
    """Збереження користувача."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (telegram_id, full_name, phone_number)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                full_name = excluded.full_name,
                phone_number = COALESCE(excluded.phone_number, users.phone_number)
        """, (telegram_id, full_name, phone_number))
        conn.commit()


def create_appointment(user_id: int, client_fio: str, phone_number: str, issue_description: str, specialist: str, date_str: str, time_str: str):
    """Збереження нового запису."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO appointments (user_id, client_fio, phone_number, issue_description, specialist, appointment_date, appointment_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, client_fio, phone_number, issue_description, specialist, date_str, time_str))
        conn.commit()
        return cursor.lastrowid


def get_all_appointments():
    """Отримання всіх записів."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM appointments")
        return cursor.fetchall()


def get_day_color(date_str: str, specialist: str = None) -> str:
    """
    Повертає кольоровий бейдж дня:
    🟩 — 0 записів (вільно)
    🟨 — від 1 до 7 записів (є хоча б 1 створений/підтверджений запис)
    🟥 — 8 і більше записів (день повністю заповнений) або ручне блокування
    """
    # 1. Перевіряємо ручний статус від адміна (якщо є таблиця day_statuses)
    with sqlite3.connect("bot_database.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM day_statuses WHERE date_str = ?", (date_str,))
        row = cursor.fetchone()
        if row:
            manual_status = row[0]
            if manual_status == "red":
                return "🔴"
            elif manual_status == "green":
                return "🟢"

        # 2. Перевіряємо формати дати
        possible_dates = [date_str]
        if "-" in date_str:
            parts = date_str.split("-")
            if len(parts) == 3:
                possible_dates.append(f"{parts[2]}.{parts[1]}.{parts[0]}")
        elif "." in date_str:
            parts = date_str.split(".")
            if len(parts) == 3:
                possible_dates.append(f"{parts[2]}-{parts[1]}-{parts[0]}")

        placeholders = ",".join(["?"] * len(possible_dates))

        # 3. Рахуємо записи без скасованих
        if specialist:
            spec_pattern = "%Денис%" if "денис" in specialist.lower() else "%Влад%" if "влад" in specialist.lower() else f"%{specialist.strip()}%"
            query = f"""
                SELECT COUNT(*) FROM appointments
                WHERE appointment_date IN ({placeholders})
                  AND specialist LIKE ?
                  AND UPPER(status) NOT IN ('CANCELLED', 'REJECTED', 'ВІДХИЛЕНО', 'СКАСОВАНО')
            """
            cursor.execute(query, (*possible_dates, spec_pattern))
        else:
            query = f"""
                SELECT COUNT(*) FROM appointments
                WHERE appointment_date IN ({placeholders})
                  AND UPPER(status) NOT IN ('CANCELLED', 'REJECTED', 'ВІДХИЛЕНО', 'СКАСОВАНО')
            """
            cursor.execute(query, tuple(possible_dates))

        count = cursor.fetchone()[0]

    # Градація кольорів:
    if count == 0:
        return "🟢"
    elif count >= 8:
        return "🔴"
    else:
        # Від 1 до 7 записів день світиться жовтим
        return "🟡"


def set_day_status(date_str: str, status: str, note: str = None):
    """Встановлення статусу дня вручну."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO day_settings (date, status, note)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                status = excluded.status,
                note = COALESCE(excluded.note, day_settings.note)
        """, (date_str, status, note))
        conn.commit()