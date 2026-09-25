"""Вызов модели в OpenAI-совместимом формате. Адрес, модель и ключ - из окружения."""

import os
import time

import requests

PAUSES = (2, 4, 8)
TIMEOUT = 120

# параметры генерации - часть конфигурации разметчика (core.dim_llm_config.params): поменялись - это новая конфигурация.
# Размышления на разметке - 88 из 92 выходных токенов при том же ответе (exploration.md)
GENERATION = {"temperature": 0, "max_tokens": 4000, "batch_size": 10, "reasoning": False}


def settings():
    base_url, model = os.getenv("LLM_BASE_URL"), os.getenv("LLM_MODEL")
    if not base_url or not model:
        raise SystemExit("нужны LLM_BASE_URL и LLM_MODEL в окружении или .env")
    return base_url.rstrip("/"), model


def api_key():
    key = os.getenv("LLM_API_KEY")
    if not key:
        raise SystemExit("нет LLM_API_KEY в окружении")
    return key


def provider_fields(base_url):
    """Поля запроса, которые у провайдеров разные: выключение размышлений и цена в usage."""
    enabled = GENERATION["reasoning"]
    if "deepseek.com" in base_url:
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    # OpenRouter
    return {"reasoning": {"enabled": enabled}, "usage": {"include": True}}

def complete(system_prompt, user_text):
    """Вернуть (текст ответа, finish_reason, цена или None)."""
    base_url, model = settings()
    key = api_key()

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
                "max_tokens": GENERATION["max_tokens"],
                "temperature": GENERATION["temperature"],
                **provider_fields(base_url),
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
