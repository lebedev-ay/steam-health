"""Вызов модели в OpenAI-совместимом формате. Адрес, модель и ключ - из окружения."""

import os
import time

import requests

PAUSES = (2, 4, 8)
TIMEOUT = 120


def settings():
    base_url, model = os.getenv("LLM_BASE_URL"), os.getenv("LLM_MODEL")
    if not base_url or not model:
        raise SystemExit("нужны LLM_BASE_URL и LLM_MODEL в окружении или .env")
    return base_url.rstrip("/"), model


def complete(system_prompt, user_text):
    """Вернуть (текст ответа, finish_reason, цена или None)."""
    base_url, model = settings()
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("нет OPENROUTER_API_KEY в окружении")

    for attempt in range(len(PAUSES) + 1):
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "max_tokens": 4000,
                "temperature": 0,
                # размышления на разметке - 88 из 92 выходных токенов при том же ответе (exploration.md). Поля reasoning и usage - расширение OpenRouter
                "reasoning": {"enabled": False},
                "usage": {"include": True},
            },
            timeout=TIMEOUT,
        )
        # 429 и 5xx - сбой на стороне провайдера, повтор с паузой; остальные ошибки повтором не лечатся
        if (response.status_code == 429 or response.status_code >= 500) and attempt < len(PAUSES):
            print(f"  ответ {response.status_code}, пауза {PAUSES[attempt]} с")
            time.sleep(PAUSES[attempt])
            continue
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        return choice["message"]["content"], choice.get("finish_reason"), (data.get("usage") or {}).get("cost")
