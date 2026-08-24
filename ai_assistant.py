import os
import json
import asyncio
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

TARGET_MODEL = "gemini-3.6-flash"


def _request_gemini_sync(prompt: str) -> str:
    """Прямий запит до актуальної моделі Gemini 3.6 Flash."""
    raw_keys = os.getenv("GEMINI_API_KEY", "").strip()
    api_keys = [k.strip().strip("'\"") for k in raw_keys.split(",") if k.strip()]

    if not api_keys:
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
    last_diagnostic = "Немає відповіді"

    for current_key in api_keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{TARGET_MODEL}:generateContent?key={current_key}"
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                candidates = resp_data.get("candidates", [])
                if candidates:
                    text = candidates[0]["content"]["parts"][0]["text"]
                    return text.replace("*", "").replace("#", "").replace("`", "").replace("_", "").strip()
                return f"⚠️ Порожня відповідь від моделі {TARGET_MODEL}."
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            last_diagnostic = f"HTTP {e.code} ({TARGET_MODEL}): {body[:250]}"
        except Exception as e:
            last_diagnostic = f"Системна помилка: {repr(e)}"

    return f"⚠️ Діагностика API: {last_diagnostic}"


async def analyze_legal_case(issue_text: str) -> str:
    """Формує структуровану довідку для адвоката."""
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
        return f"⚠️ Помилка виконання: {repr(e)}"