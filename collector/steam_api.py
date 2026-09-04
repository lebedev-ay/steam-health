import time

import requests

USER_AGENT = "steam-health/0.1"
TIMEOUT = 30


def get(url, params, pauses=(2, 4, 8)):
    """Запрос к Steam API с ретраями. None, если не ответил за все попытки."""
    payload, _ = get_with_status(url, params, pauses)
    return payload


def get_with_status(url, params, pauses=(2, 4, 8)):
    """То же, но с кодом ответа: raw.appdetails хранит его рядом с телом."""
    status = None
    for attempt in range(len(pauses) + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            status = response.status_code
            response.raise_for_status()
            return response.json(), status
        except requests.RequestException as e:
            if e.response is not None:
                status = e.response.status_code
            print(f"  ошибка запроса, попытка {attempt + 1}: {e}")
            if attempt < len(pauses):
                time.sleep(pauses[attempt])

    return None, status
