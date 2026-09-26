"""Отбор отзывов в разметку: порог длины и дневной лимит на игру. Без базы - это и тестируется."""

import hashlib
import statistics
from collections import defaultdict
from datetime import timedelta

# статусы, после которых текущий текст этой конфигурацией не размечается; failed берётся снова
DONE = ("labeled", "no_opinion")

SPIKE_WINDOW = 28


def day_order(recommendation_id):
    # порядок внутри дня воспроизводим и не зависит от порядка загрузки: при повышении лимита добираются только новые позиции
    return hashlib.md5(str(recommendation_id).encode()).hexdigest()


def day_limits(content, day_limit, spike_factor, spike_min_abs, spike_limit):
    """Адаптивный лимит: {день: {content, median, spike, limit}} для каждого дня из content ({день: содержательных отзывов}).

    Медиана - по SPIKE_WINDOW предыдущим календарным дням без текущего; день без отзывов считается нулём, иначе тихие периоды выпадали бы из медианы.
    Первые SPIKE_WINDOW дней ряда медианы не имеют: всплесков там нет, лимит обычный.
    """
    if not content:
        return {}
    start = min(content)
    out = {}
    for day, n in content.items():
        median = None
        if day >= start + timedelta(days=SPIKE_WINDOW):
            median = statistics.median(content.get(day - timedelta(days=k), 0) for k in range(1, SPIKE_WINDOW + 1))
        spike = median is not None and n >= spike_factor * median and n >= spike_min_abs
        out[day] = {"content": n, "median": median, "spike": spike, "limit": spike_limit if spike else day_limit}
    return out


def plan(rows, min_length, day_limit, limits=None):
    """rows - словари recommendation_id, day, length, status (None - не размечался). limits - {день: лимит} поверх day_limit.

    Вернуть to_label (с day_rank) и счётчики для отчёта. Короткие отзывы только считаются: в базу не пишутся и в модель не уходят.
    Ранг считается по всем отзывам дня не короче порога, включая уже размеченные, - иначе размеченные уступали бы места и лимит бы расползался.
    Поэтому поднятый лимит дня добирает только следующие по порядку отзывы, размеченные остаются как есть.
    """
    limits = limits or {}
    out = {"to_label": [], "too_short": 0, "over_limit": 0, "done": 0, "retry": 0}
    by_day = defaultdict(list)

    for r in rows:
        if r["length"] < min_length:
            out["too_short"] += 1
        else:
            by_day[r["day"]].append(r)

    for day, day_rows in by_day.items():
        day_rows.sort(key=lambda r: day_order(r["recommendation_id"]))
        limit = limits.get(day, day_limit)
        for rank, r in enumerate(day_rows, start=1):
            if r["status"] in DONE:
                out["done"] += 1
            elif rank > limit:
                out["over_limit"] += 1
            else:
                if r["status"] == "failed":
                    out["retry"] += 1
                out["to_label"].append({**r, "day_rank": rank})

    return out


def plan_listed(rows):
    """Отзывы из явного списка (эталон): без порога длины и дневного лимита, day_rank не заполняется."""
    out = {"to_label": [], "too_short": 0, "over_limit": 0, "done": 0, "retry": 0}
    for r in rows:
        if r["status"] in DONE:
            out["done"] += 1
        else:
            out["retry"] += r["status"] == "failed"
            out["to_label"].append({**r, "day_rank": None})
    return out


def cap(items, limit):
    """Потолок на запуск по всем играм: свежие дни первыми, внутри дня - по рангу. Вернуть (взятые, сколько осталось).

    Свежее - то, что на дашборде смотрят первым; история новой игры добирается следующими запусками, уже размеченное они пропускают.
    """
    ordered = sorted(items, key=lambda r: (-r["day"].toordinal(), r["day_rank"] or 0, r["recommendation_id"]))
    return ordered[:limit], max(len(ordered) - limit, 0)
