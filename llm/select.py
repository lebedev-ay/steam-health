"""Отбор отзывов в разметку: порог длины и дневной лимит на игру. Без базы - это и тестируется."""

import hashlib
from collections import defaultdict

# состояние разметки текущего текста этой конфигурацией; failed и too_short берутся снова
DONE = ("labeled", "no_opinion")


def day_order(recommendation_id):
    # порядок внутри дня воспроизводим и не зависит от порядка загрузки: при повышении лимита добираются только новые позиции
    return hashlib.md5(str(recommendation_id).encode()).hexdigest()


def plan(rows, min_length, day_limit):
    """rows - словари recommendation_id, day, length, status (None - не размечался).

    Вернуть словарь списков: to_label (с day_rank), too_short (новые, отметить без модели), и счётчики для отчёта.
    Ранг считается по всем отзывам дня не короче порога, включая уже размеченные, - иначе размеченные уступали бы места и лимит бы расползался.
    """
    out = {"to_label": [], "too_short": [], "short_known": 0, "over_limit": 0, "done": 0, "retry": 0}
    by_day = defaultdict(list)

    for r in rows:
        if r["length"] < min_length:
            if r["status"] is None or r["status"] == "failed":
                out["too_short"].append(r)
            elif r["status"] == "too_short":
                out["short_known"] += 1
            else:
                out["done"] += 1   # размечен при прежнем, меньшем пороге
            continue
        by_day[r["day"]].append(r)

    for day_rows in by_day.values():
        day_rows.sort(key=lambda r: day_order(r["recommendation_id"]))
        for rank, r in enumerate(day_rows, start=1):
            if r["status"] in DONE:
                out["done"] += 1
            elif rank > day_limit:
                out["over_limit"] += 1
            else:
                if r["status"] is not None:
                    out["retry"] += 1
                out["to_label"].append({**r, "day_rank": rank})

    return out
