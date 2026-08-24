import os
import json
import asyncio
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

RAW_KEYS = os.getenv("GEMINI_API_KEY", "").strip()
API_KEYS = [k.strip().strip("'\"") for k in RAW_KEYS.split(",") if k.strip()]


def _request_gemini_sync(prompt: str) -> str:
    """Прямий запит до Gemini з детальним поверненням помилки для діагностики."""
    if not API_KEYS:
        return "⚠️ Не налаштовано GEMINI_API_KEY."

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.3
        }
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    
    last_error = "Невідома помилка"

    for current_key in API_KEYS:
        # Перевіряємо обидва варіанти передачі (URL та заголовок)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={current_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": current_key
        }

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                candidates = resp_data.get("candidates", [])
                if candidates:
                    text = candidates[0]["content"]["parts"][0]["text"]
                    return text.replace("*", "").replace("#", "").replace("`", "").replace("_", "").strip()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {e.code}: {err_body[:200]}"
            continue
        except Exception as e:
            last_error = f"Системна помилка: {repr(e)}"
            continue

    return f"⚠️ Деталі помилки Gemini: {last_error}"


async def analyze_legal_case(issue_text: str) -> str:
    """Формує структуровану довідку для адвоката."""
    if not API_KEYS:
        return "⚠️ AI-аналітика недоступна (не налаштовано GEMINI_API_KEY)."

    if not issue_text or issue_text.strip() in ("", "Не вказано"):
        return "ℹ️ Клієнт не надав опису проблеми."

    prompt = (
        "Ти помічник українського адвоката. Зроби стислий аналіз проблеми клієнта:\n"
        f"\"{issue_text}\"\n\n"
        "Сформуй структуру чистим текстом без зірочок і спецсимволів:\n"
        "1. Галузь права:\n"
        "2. Статті законів та кодексів України:\n"
        "3. Вектор дій адвоката:\n"
        "4. Необхідні документи від клієнта:"
    )

    try:
        result = await asyncio.to_thread(_request_gemini_sync, prompt)
        return result
    except Exception as e:
        return f"Помилка обробки: {repr(e)}"