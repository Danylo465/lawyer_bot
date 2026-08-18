import sqlite3
DB_NAME = "bot_database.db"

def clear_test_data():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # 1. Очищаємо всі тестові записи на консультації
        cursor.execute("DELETE FROM appointments")
        
        # 2. Скидаємо лічильник ID (щоб нові записи знову починалися з id=1)
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='appointments'")
        
        # 3. Очищаємо ручні блокування днів у світлофорі (за бажанням)
        cursor.execute("DELETE FROM day_settings")
        
        conn.commit()
        print(" Все тестові записи та налаштування успішно видалено! База чиста.")

if __name__ == "__main__":
    clear_test_data()