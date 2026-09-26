"""Детектор точек перелома и события рядом с ними. Общий для дашборда (web/app.py) и выводов по переломам (llm/verdict.py)."""

from datetime import datetime

from db import query
from text import plural


# на ровном ряде разброс сдвигов нулевой, порог тоже, и нестрогое сравнение объявляло переломом каждый день с нулевым сдвигом
MIN_SHIFT_PP = 1.0
MIN_SCORED_DAYS = 30


def find_change_points(smoothed, half_window=7, min_gap=7, sensitivity=1.5):
    """
    Ищет точки перелома: где среднее ПОСЛЕ заметно отличается от среднего ДО. sensitivity - сколько сигм считать переломом.
    Возвращает найденные точки и причину, если искать было не на чем.
    """
    n = len(smoothed)
    scores = [None] * n

    for i in range(n):
        before = [s["pct"] for s in smoothed[max(0, i - half_window):i]
                  if s["pct"] is not None]
        after = [s["pct"] for s in smoothed[i:i + half_window]
                 if s["pct"] is not None]

        if len(before) < half_window // 2 or len(after) < half_window // 2:
            continue

        scores[i] = sum(after) / len(after) - sum(before) / len(before)

    clean = [abs(s) for s in scores if s is not None]
    if len(clean) < MIN_SCORED_DAYS:
        return [], (f"мало данных: сдвиг посчитан для {len(clean)} "
                    f"{plural(len(clean), 'день', 'дня', 'дней')} из {n}, "
                    f"детектору нужно не меньше {MIN_SCORED_DAYS}")

    mean = sum(clean) / len(clean)
    var = sum((x - mean) ** 2 for x in clean) / len(clean)
    threshold = mean + sensitivity * (var ** 0.5)

    candidates = [
        (i, scores[i]) for i in range(n)
        if scores[i] is not None
        and abs(scores[i]) > threshold
        and abs(scores[i]) >= MIN_SHIFT_PP
    ]
    candidates.sort(key=lambda x: -abs(x[1]))

    chosen = []
    for i, score in candidates:
        if all(abs(i - j) >= min_gap for j, _ in chosen):
            chosen.append((i, score))

    return sorted(chosen), None


# значимость патча меряется весом: тип события ничего не говорит о его величине, и хотфикс весом 0.1 проходил как крупный патч
SIGNIFICANT_WEIGHT = 2


# вес - длина патчноута относительно медианы патчей игры, и сезон с дополнением им не измеряются: они редки, и редкость их и делает заметными. Маркетинг, блоги и служебное - фон при любом весе
ALWAYS_SIGNIFICANT = ("season_start", "expansion")
NEVER_SIGNIFICANT = ("marketing", "blog", "service")


# отклик данных на событие: объём отзывов и доля позитива в окне +-3 дня. Доля считается суммами, а не средним дневных долей - запись 008. Пороги взяты по 90-му перцентилю обеих величин на всех играх
RESPONSE_WINDOW = 3
RESPONSE_VOLUME_RATIO = 2.0
RESPONSE_SHIFT_PP = 12
RESPONSE_MIN_REVIEWS = 30


def is_significant_event(e):
    if e["event_type"] in ALWAYS_SIGNIFICANT:
        return True
    if e["event_type"] in NEVER_SIGNIFICANT:
        return False
    return (e["weight"] or 0) >= SIGNIFICANT_WEIGHT


def has_response(day_index, totals, positives, day):
    i = day_index.get(day)
    if i is None:
        return False
    lo = max(0, i - RESPONSE_WINDOW)
    before, after = totals[lo:i], totals[i:i + RESPONSE_WINDOW]
    if not before or not after:
        return False

    bt, at = sum(before), sum(after)
    if bt and (at / len(after)) / (bt / len(before)) >= RESPONSE_VOLUME_RATIO:
        return True

    # на десятке отзывов доля скачет сама по себе, сдвиг такого окна ничего не значит
    if min(bt, at) < RESPONSE_MIN_REVIEWS:
        return False
    bp, ap = sum(positives[lo:i]), sum(positives[i:i + RESPONSE_WINDOW])
    return abs(100 * ap / at - 100 * bp / bt) >= RESPONSE_SHIFT_PP


def build_series(app_id, smoothing):
    # дневной агрегат уже посчитан витриной; календарь нужен, чтобы дни без отзывов попадали в ряд нулями
    raw_daily = query("""
        with bounds as (
            select min(day) as d_from, max(day) as d_to
            from marts.review_daily
            where app_id = %s
        ),
        calendar as (
            select generate_series(d_from, d_to, interval '1 day')::date as day
            from bounds
        )
        select c.day,
               coalesce(d.review_count, 0) as total,
               coalesce(d.positive_count, 0) as positive
        from calendar c
        left join marts.review_daily d
               on d.app_id = %s and d.day = c.day
        order by c.day
    """, (app_id, app_id))

    if not raw_daily:
        return [], [], 0, 0

    # ширина окна: обратно пропорциональна медианному объёму
    volumes = sorted(r["total"] for r in raw_daily)
    median = volumes[len(volumes) // 2]

    if smoothing == "off":
        half = 0
    elif smoothing == "auto":
        if median >= 100:
            half = 1      # окно 3 дня
        elif median >= 30:
            half = 3      # окно 7 дней
        elif median >= 10:
            half = 7      # окно 15 дней
        else:
            half = 14     # окно 29 дней
    else:
        half = int(smoothing) // 2

    smoothed = []
    for i, row in enumerate(raw_daily):
        lo = max(0, i - half)
        hi = min(len(raw_daily), i + half + 1)
        window = raw_daily[lo:hi]

        pos = sum(w["positive"] for w in window)
        tot = sum(w["total"] for w in window)

        smoothed.append({
            "day": row["day"].isoformat(),
            "total": row["total"],
            "positive": row["positive"],
            "pct": round(100 * pos / tot, 1) if tot else None,
        })

    # база - медиана сглаженной доли за 90 предыдущих дней: обычный для игры уровень, от которого видно отклонение
    BASE_DAYS = 90
    for i, row in enumerate(smoothed):
        history = [s["pct"] for s in smoothed[max(0, i - BASE_DAYS):i] if s["pct"] is not None]
        row["base"] = sorted(history)[len(history) // 2] if row["pct"] is not None and len(history) >= 14 else None

    return smoothed, raw_daily, half, median


def build_events(app_id, raw_daily):
    """События игры и платформы в границах ряда отзывов: событию вне его нечего объяснять.

    У события игры флаг shown - место на графике: значимое по правилу is_significant_event или с откликом в данных рядом.
    Совпадение по времени причиной не является: всплеск объёма бывает от чего угодно. Это правило показа, а не утверждение о влиянии.
    Детектору и выводам нужны все события, включая фоновые: скрытый на графике слабый патч тоже может оказаться рядом с переломом.
    """
    # distinct нужен потому, что Steam выпускает один анонс под несколькими gid, а маркер ему положен один
    events = query("""
        select distinct
               (p.published_at at time zone 'utc')::date as day,
               p.event_type,
               p.title,
               p.weight
        from core.fct_patch p
        join core.dim_game g on g.game_sk = p.game_sk
        where g.app_id = %s
          and (p.published_at at time zone 'utc')::date between %s and %s
        order by 1
    """, (app_id, raw_daily[0]["day"], raw_daily[-1]["day"]))

    day_index = {r["day"]: i for i, r in enumerate(raw_daily)}
    totals = [r["total"] for r in raw_daily]
    positives = [r["positive"] for r in raw_daily]
    for e in events:
        e["shown"] = is_significant_event(e) or has_response(day_index, totals, positives, e["day"])

    # общие для всех игр, не зависят от app_id. Дата приблизительная (по публикации заметки)
    platform_events = query("""
        select event_date, event_type, title
        from core.dim_platform_event
        where event_date >= %s and event_date <= %s
        order by event_date
    """, (raw_daily[0]["day"], raw_daily[-1]["day"]))

    return events, platform_events


def attach_events(change_points, smoothed, cp_events, platform_events):
    cp_out = []
    for idx, score in change_points:
        day = smoothed[idx]["day"]
        day_date = datetime.fromisoformat(day).date()

        nearby = [
            e for e in cp_events
            if abs((e["day"] - day_date).days) <= 3
        ]
        major = [e for e in nearby if is_significant_event(e)]
        minor = [e for e in nearby if not is_significant_event(e)]

        platform_nearby = [
            e for e in platform_events
            if abs((e["event_date"] - day_date).days) <= 3
        ]
        platform_event = None
        if platform_nearby:
            closest = min(platform_nearby,
                          key=lambda e: abs((e["event_date"] - day_date).days))
            platform_event = {
                "date": closest["event_date"].isoformat(),
                "type": closest["event_type"],
                "title": closest["title"],
            }

        cp_out.append({
            "day": day,
            "score": round(score, 1),
            "events": [
                {"type": e["event_type"], "title": e["title"],
                 "weight": float(e["weight"]) if e["weight"] is not None else None}
                for e in major
            ],
            "events_minor": [
                {"type": e["event_type"], "title": e["title"]}
                for e in minor
            ],
            "platform_event": platform_event,
        })

    return cp_out
