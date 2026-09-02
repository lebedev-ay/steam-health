import time

import requests

USER_AGENT = "steam-health/0.1"
TIMEOUT = 30


def get(url, params, pauses=(2, 4, 8)):
    """Запрос к Steam API с ретраями. None, если не ответил за все попытки."""
    for attempt in range(len(pauses) + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"  ошибка запроса, попытка {attempt + 1}: {e}")
            if attempt < len(pauses):
                time.sleep(pauses[attempt])

    return None
