"""Вызов модели в OpenAI-совместимом формате. Адрес, модель и ключ - из окружения."""

import os
import time

import requests

PAUSES = (2, 4, 8)
TIMEOUT = 120

# параметры генерации - часть конфигурации разметчика (core.dim_llm_config.params): поменялись - это новая конфигурация.
# Размышления на разметке - 88 из 92 выходных токенов при том же ответе (exploration.md)
GENERATION = {"temperature": 0, "max_tokens": 4000, "batch_size": 10, "reasoning": False}

# для оценки до вызова. Замер на эталоне (45 отзывов, deepseek-flash): английский промпт 5.5 символа на токен, тексты на разных языках - 3,
# ответ 61 токен на отзыв. Фактические токены печатает каждый прогон - по ним и уточнять
PROMPT_CHARS_PER_TOKEN = 5.5
TEXT_CHARS_PER_TOKEN = 3.0
OUTPUT_TOKENS_PER_REVIEW = 60
REVIEW_TAG_CHARS = len('<review n="10"></review>\n')


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


def prices():
    """Цены за 1 млн токенов из окружения. None - цена неизвестна: считать по нулям значило бы выдать $0 за правду."""
    try:
        price_in, price_out = float(os.getenv("LLM_PRICE_INPUT")), float(os.getenv("LLM_PRICE_OUTPUT"))
    except (TypeError, ValueError):
        return None
    cached = os.getenv("LLM_PRICE_INPUT_CACHED")
    # без отдельной цены кэшированный вход считается по полной - оценка сверху
    return {"input": price_in, "output": price_out, "input_cached": float(cached) if cached else price_in}


def tokens(usage):
    """(вход, из него из кэша, выход). Кэш у DeepSeek - prompt_cache_hit_tokens, в формате OpenAI - prompt_tokens_details.cached_tokens."""
    usage = usage or {}
    cached = (usage.get("prompt_cache_hit_tokens")
              or (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return usage.get("prompt_tokens") or 0, cached, usage.get("completion_tokens") or 0


def reasoning_tokens(usage):
    """Токены размышлений внутри выхода. На разметке размышления выключены, и счётчик обязан быть нулевым."""
    return ((usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0


def price_of(n_in, n_cached, n_out, price):
    return ((n_in - n_cached) * price["input"] + n_cached * price["input_cached"] + n_out * price["output"]) / 1e6


def cost(usage, price):
    """Цена вызова: usage.cost, если провайдер его вернул, иначе по токенам и ценам окружения; None - неизвестна."""
    if usage and usage.get("cost") is not None:
        return usage["cost"]
    if price is None:
        return None
    return price_of(*tokens(usage), price)


def new_spend():
    return {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost": 0.0}


def add_spend(total, part):
    """Прибавить расход part к total. Цена None заразна: одна неизвестная делает неизвестной всю сумму."""
    for key in ("input", "cached", "output", "reasoning"):
        total[key] += part[key]
    total["cost"] = None if part["cost"] is None or total["cost"] is None else total["cost"] + part["cost"]


def spend_of(usage, price):
    """Расход одного вызова по usage ответа."""
    n_in, n_cached, n_out = tokens(usage)
    return {"input": n_in, "cached": n_cached, "output": n_out,
            "reasoning": reasoning_tokens(usage), "cost": cost(usage, price)}


def money(value):
    return "цена неизвестна" if value is None else f"${value:.4f}"


def estimate(prompt, text_chars, n, price):
    """Оценка цены разметки n отзывов до вызова; None - цены не заданы."""
    if price is None or n == 0:
        return None if price is None else 0.0
    batches = -(-n // GENERATION["batch_size"])
    prompt_tokens = len(prompt) / PROMPT_CHARS_PER_TOKEN
    n_in = batches * prompt_tokens + (text_chars + n * REVIEW_TAG_CHARS) / TEXT_CHARS_PER_TOKEN
    # системный промпт общий у всех пачек: после первой он обычно берётся из кэша провайдера
    n_cached = (batches - 1) * prompt_tokens
    return price_of(n_in, n_cached, n * OUTPUT_TOKENS_PER_REVIEW, price)


def provider_fields(base_url):
    """Поля запроса, которые у провайдеров разные: выключение размышлений и цена в usage."""
    enabled = GENERATION["reasoning"]
    if "deepseek.com" in base_url:
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    # OpenRouter
    return {"reasoning": {"enabled": enabled}, "usage": {"include": True}}

def complete(system_prompt, user_text):
    """Вернуть (текст ответа, finish_reason, usage)."""
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
        return choice["message"]["content"], choice.get("finish_reason"), data.get("usage") or {}
