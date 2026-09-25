"""Отбор отзывов в разметку: порог длины и дневной лимит на игру. Без базы - это и тестируется."""

import hashlib
from collections import defaultdict

# статусы, после которых текущий текст этой конфигурацией не размечается; failed берётся снова
DONE = ("labeled", "no_opinion")


def day_order(recommendation_id):
    # порядок внутри дня воспроизводим и не зависит от порядка загрузки: при повышении лимита добираются только новые позиции
    return hashlib.md5(str(recommendation_id).encode()).hexdigest()


def plan(rows, min_length, day_limit):
    """rows - словари recommendation_id, day, length, status (None - не размечался).

    Вернуть to_label (с day_rank) и счётчики для отчёта. Короткие отзывы только считаются: в базу не пишутся и в модель не уходят.
    Ранг считается по всем отзывам дня не короче порога, включая уже размеченные, - иначе размеченные уступали бы места и лимит бы расползался.
    """
    out = {"to_label": [], "too_short": 0, "over_limit": 0, "done": 0, "retry": 0}
    by_day = defaultdict(list)

    for r in rows:
        if r["length"] < min_length:
            out["too_short"] += 1
        else:
            by_day[r["day"]].append(r)

    for day_rows in by_day.values():
        day_rows.sort(key=lambda r: day_order(r["recommendation_id"]))
        for rank, r in enumerate(day_rows, start=1):
            if r["status"] in DONE:
                out["done"] += 1
            elif rank > day_limit:
                out["over_limit"] += 1
            else:
                if r["status"] == "failed":
                    out["retry"] += 1
                out["to_label"].append({**r, "day_rank": rank})

    return out
