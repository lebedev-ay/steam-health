"""Данные для страниц дашборда: обзор всех игр, страница игры и то, во что на ней можно углубиться."""

import re
from datetime import date, timedelta
from functools import lru_cache

from change_points import (NEVER_SIGNIFICANT, attach_events, build_events, build_series,
                           find_change_points)
from db import query

# окна вокруг перелома и события - те же 7 дней, что в выводах (llm/verdict_check.py)
WINDOW = 7
SPARK_WEEKS = 26
REVIEWS_PAGE = 20
QUOTES = 4
WORDS = 14
WORDS_BASE_DAYS = 90
# сверх стоп-слов Postgres: общие слова отзывов, которые есть везде и ничего не говорят о конкретной игре
COMMON_WORDS = [
    "game", "games", "play", "playing", "played", "every", "since", "also", "would", "really", "even", "much", "get", "got",
    "one", "like", "just", "still", "make", "made", "lot", "lots", "thing", "things", "way", "time", "good", "bad", "well",
    "gets", "never", "old", "new", "takes", "take", "keep", "keeps", "since", "many", "first", "back", "need",
    "игра", "игры", "игре", "игру", "игрой", "играть", "очень", "просто", "это", "всё", "все", "ещё", "еще", "может", "которые",
]

# номера опор в тексте вывода нужны для проверки по уликам, читателю дашборда они ничего не говорят
SUPPORT_REFS_RE = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")

# отрывки и цитаты: дашборд русскоязычный, сначала русские отзывы, затем английские
LANGUAGE_ORDER = "case l.language_code when 'russian' then 0 when 'english' then 1 else 2 end"

# теги отзыва активной конфигурацией разметки - прямо из ядра: представления витрин считают окно по всей разметке, а здесь нужен один отзыв
REVIEW_TAGS = """
    (select json_agg(json_build_object('aspect', da.aspect_id, 'sentiment', ra.sentiment) order by ra.importance)
     from core.review_text_version v
     join core.fct_review_labeling fl on fl.review_text_sk = v.review_text_sk
     join marts.llm_config_active c on c.llm_config_sk = fl.llm_config_sk
     join core.fct_review_aspect ra on ra.labeling_sk = fl.labeling_sk
     join core.dim_aspect da on da.aspect_sk = ra.aspect_sk
     where v.recommendation_id = f.recommendation_id and v.is_current and da.aspect_id <> 'other')
"""


def games_overview():
    """Все игры с долей позитива за последние 30 дней, прошлые 30 и недельной кривой за полгода.

    «Последние» - от последнего дня с отзывами у каждой игры: у давно не обновлявшейся игры окно не должно оказаться пустым.
    """
    games = query("""
        with last as (select app_id, max(day) as last_day from marts.review_daily group by app_id)
        select g.app_id, g.game_name, g.genres, g.developers, g.collection_status, l.last_day,
               exists (select 1 from marts.review_labeling_daily r join marts.llm_config_active c using (llm_config_sk)
                       where r.app_id = g.app_id and r.labeled_count > 0) as has_llm,
               coalesce(sum(d.review_count), 0)::int as reviews,
               sum(d.positive_count) filter (where d.day > l.last_day - 30)::int as positive_30,
               sum(d.review_count) filter (where d.day > l.last_day - 30)::int as reviews_30,
               sum(d.positive_count) filter (where d.day <= l.last_day - 30 and d.day > l.last_day - 60)::int as positive_prev,
               sum(d.review_count) filter (where d.day <= l.last_day - 30 and d.day > l.last_day - 60)::int as reviews_prev
        from marts.dim_game_current g
        left join last l on l.app_id = g.app_id
        left join marts.review_daily d on d.app_id = g.app_id
        group by g.app_id, g.game_name, g.genres, g.developers, g.collection_status, l.last_day
        order by g.game_name
    """)
    weeks = query("""
        with last as (select app_id, max(day) as last_day from marts.review_daily group by app_id)
        select d.app_id, date_trunc('week', d.day)::date as week,
               sum(d.positive_count)::int as positive, sum(d.review_count)::int as reviews
        from marts.review_daily d
        join last l on l.app_id = d.app_id
        where d.day > l.last_day - %s
        group by 1, 2
        order by 1, 2
    """, (SPARK_WEEKS * 7,))
    spark = {}
    for w in weeks:
        spark.setdefault(w["app_id"], []).append(round(100 * w["positive"] / w["reviews"], 1) if w["reviews"] else None)
    for g in games:
        g["spark"] = spark.get(g["app_id"], [])
    return games


def window(raw_daily, lo, hi):
    """(отзывов, доля положительных в процентах) за [lo, hi) суммами по дням - как в уликах вывода."""
    rows = [r for r in raw_daily if lo <= r["day"] < hi]
    total = sum(r["total"] for r in rows)
    return total, (round(100 * sum(r["positive"] for r in rows) / total) if total else None)


def around(raw_daily, day):
    """Неделя до дня и неделя после, начиная с него."""
    before = window(raw_daily, day - timedelta(days=WINDOW), day)
    after = window(raw_daily, day, day + timedelta(days=WINDOW))
    return {"reviews_before": before[0], "positive_before": before[1],
            "reviews_after": after[0], "positive_after": after[1]}


def verdict_view(v):
    """Вывод для карточки перелома. Не прошедший проверку кодом - без текста: его писала модель, и проверка его не пропустила."""
    card = {"preliminary": v["status"] == "preliminary", "checked": v["checks_passed"]}
    if v["checks_passed"]:
        card["what_happened"] = SUPPORT_REFS_RE.sub("", v["what_happened"]).strip()
        if v["author"] == "model":
            card["what_players_say"] = SUPPORT_REFS_RE.sub("", v["what_players_say"] or "").strip()
            card["excerpts"] = [e["text"] for e in v["excerpts"]]
    return card


def game_page(app_id, smoothing, sensitivity):
    """Всё для страницы игры одним ответом; None - игры нет в базе."""
    info = query("""
        select app_id, game_name, developers, publishers, genres, release_date_parsed as release_date,
               metacritic_score, collection_status
        from marts.dim_game_current where app_id = %s
    """, (app_id,))
    if not info:
        return None

    smoothed, raw_daily, half, median = build_series(app_id, smoothing)
    out = {"game": info[0], "daily": smoothed, "window": half * 2 + 1, "median_volume": median,
           "events": [], "platform_events": [], "updates": [], "change_points": [], "change_points_note": None,
           "segments": segments(app_id), "aspects": aspects(app_id), "digest": digest(app_id),
           "lengths": lengths(app_id)}
    if not raw_daily:
        out["change_points_note"] = "по этой игре ещё нет собранных отзывов"
        return out

    events, platform_events = build_events(app_id, raw_daily)
    found, out["change_points_note"] = find_change_points(smoothed, sensitivity=sensitivity)
    verdicts = {v["change_date"]: verdict_view(v) for v in query("""
        select change_date, status, author, checks_passed, what_happened, what_players_say, excerpts
        from marts.change_point_verdict_current where app_id = %s
    """, (app_id,))}

    # все события: сколько из них поместится на график, решает браузер по ширине и приближению
    out["events"] = [{"day": e["day"], "type": e["event_type"], "title": e["title"], "weight": e["weight"],
                      "significant": e["significant"], "responsive": e["responsive"]} for e in events]
    out["platform_events"] = [{"day": e["event_date"], "type": e["event_type"], "title": e["title"]}
                              for e in platform_events]
    # реакция на каждую новость игры, кроме фона (маркетинг, блоги, служебное): таблица для тех, кто хочет сравнить патчи между собой
    out["updates"] = [{"day": e["day"], "type": e["event_type"], "title": e["title"], "weight": e["weight"],
                       "shown": e["shown"], **around(raw_daily, e["day"])}
                      for e in events if e["event_type"] not in NEVER_SIGNIFICANT]
    out["change_points"] = [
        {**cp, **around(raw_daily, date.fromisoformat(cp["day"])), "verdict": verdicts.get(date.fromisoformat(cp["day"]))}
        for cp in attach_events(found, smoothed, events, platform_events)
    ]
    return out


def segments(app_id):
    """{разрез: [{segment, reviews, positive}]} в естественном порядке; языки - по числу отзывов."""
    out = {}
    for r in query("""
        select dimension, segment, review_count as reviews, positive_count as positive
        from marts.review_segment where app_id = %s
        order by dimension, sort_order, review_count desc
    """, (app_id,)):
        out.setdefault(r.pop("dimension"), []).append(r)
    return out


def aspects(app_id):
    """Темы отзывов по LLM-разметке активной конфигурации; None - игра не размечалась.

    Доли считаются среди размеченных отзывов: разметка идёт выборкой с дневным лимитом, и в ней важны пропорции, а не число.
    """
    total = query("""
        select sum(d.labeled_count)::int as labeled, min(d.day) filter (where d.labeled_count > 0) as since,
               max(d.day) filter (where d.labeled_count > 0) as until
        from marts.review_labeling_daily d
        join marts.llm_config_active c on c.llm_config_sk = d.llm_config_sk
        where d.app_id = %s
    """, (app_id,))[0]
    if not total["labeled"]:
        return None

    items = query("""
        select a.category_id, a.aspect_id, sum(a.review_count)::int as mentions,
               sum(a.positive_count)::int as positive, sum(a.negative_count)::int as negative,
               sum(a.mixed_count)::int as mixed
        from marts.review_aspect_daily a
        join marts.llm_config_active c on c.llm_config_sk = a.llm_config_sk
        where a.app_id = %s and a.aspect_id not in ('overall_impression', 'other')
        group by a.category_id, a.aspect_id
        order by mentions desc
    """, (app_id,))

    # категории по месяцам: доля размеченных отзывов с критикой (минус или «±») - тепловая карта больных мест во времени
    months = query("""
        with labeled as (
            select date_trunc('month', d.day)::date as month, sum(d.labeled_count) as n
            from marts.review_labeling_daily d
            join marts.llm_config_active c on c.llm_config_sk = d.llm_config_sk
            where d.app_id = %(app)s
            group by 1
        )
        select date_trunc('month', a.day)::date as month, a.category_id,
               sum(a.negative_count + a.mixed_count)::int as critique, sum(a.positive_count)::int as praise,
               max(l.n)::int as labeled
        from marts.review_category_daily a
        join marts.llm_config_active c on c.llm_config_sk = a.llm_config_sk
        join labeled l on l.month = date_trunc('month', a.day)::date
        where a.app_id = %(app)s and a.category_id not in ('overall', 'other')
        group by 1, 2
        order by 1, 2
    """, {"app": app_id})

    return {**total, "items": items, "months": months}


def aspect_detail(app_id, aspect_id):
    """Одна тема игры: по месяцам сколько хвалят и ругают среди размеченных, и цитаты с каждой стороны."""
    months = query("""
        with labeled as (
            select date_trunc('month', d.day)::date as month, sum(d.labeled_count)::int as labeled
            from marts.review_labeling_daily d
            join marts.llm_config_active c on c.llm_config_sk = d.llm_config_sk
            where d.app_id = %(app)s and d.labeled_count > 0
            group by 1
        )
        select l.month, l.labeled,
               coalesce(sum(a.positive_count), 0)::int as positive,
               coalesce(sum(a.negative_count), 0)::int as negative,
               coalesce(sum(a.mixed_count), 0)::int as mixed
        from labeled l
        left join (marts.review_aspect_daily a join marts.llm_config_active c on c.llm_config_sk = a.llm_config_sk)
               on a.app_id = %(app)s and a.aspect_id = %(aspect)s and date_trunc('month', a.day)::date = l.month
        group by l.month, l.labeled
        order by l.month
    """, {"app": app_id, "aspect": aspect_id})

    # цитаты - текст той версии, что размечалась: по ней и поставлен тег
    quotes = query(f"""
        select sentiment, text, votes_up, language, day, minutes
        from (
            select ra.sentiment, v.review_body as text, f.votes_up, l.language_code as language,
                   (f.created_at at time zone 'utc')::date as day, f.playtime_at_review_min as minutes,
                   row_number() over (partition by ra.sentiment
                                      order by {LANGUAGE_ORDER}, f.votes_up desc, f.recommendation_id) as rn
            from core.fct_review_aspect ra
            join core.dim_aspect da on da.aspect_sk = ra.aspect_sk
            join core.fct_review_labeling fl on fl.labeling_sk = ra.labeling_sk
            join marts.llm_config_active c on c.llm_config_sk = fl.llm_config_sk
            join core.review_text_version v on v.review_text_sk = fl.review_text_sk and v.is_current
            join core.fct_review f on f.recommendation_id = v.recommendation_id
            join core.dim_game g on g.game_sk = f.game_sk
            join core.dim_language l on l.language_sk = f.language_sk
            where g.app_id = %(app)s and da.aspect_id = %(aspect)s and ra.sentiment in ('+', '-')
              and char_length(v.review_body) between 40 and 700
        ) q
        where rn <= %(n)s
        order by sentiment, rn
    """, {"app": app_id, "aspect": aspect_id, "n": QUOTES})
    return {"aspect_id": aspect_id, "months": months,
            "praise": [q for q in quotes if q["sentiment"] == "+"],
            "critique": [q for q in quotes if q["sentiment"] == "-"]}


def reviews(app_id, since, until, vote=None, language=None, sort="helpful", offset=0, text=None):
    """Страница отзывов с текстом за [since, until): фильтры по оценке, языку и слову в тексте, теги разметки у размеченных."""
    conds = ["g.app_id = %(app)s", "f.created_at >= %(since)s", "f.created_at < %(until)s",
             "char_length(btrim(coalesce(t.review_body, ''))) >= 20"]
    if vote is not None:
        conds.append("f.is_voted_up = %(up)s")
    if language:
        conds.append("l.language_code = %(language)s")
    if text:
        conds.append("t.review_body ilike %(text)s")
    order = "f.votes_up desc, f.created_at desc" if sort == "helpful" else "f.created_at desc"
    rows = query(f"""
        select f.recommendation_id as id, (f.created_at at time zone 'utc')::date as day, f.is_voted_up as up,
               f.votes_up, f.playtime_at_review_min as minutes, l.language_code as language,
               f.dev_responded_at is not null as answered, t.review_body as text,
               {REVIEW_TAGS} as tags
        from core.fct_review f
        join core.dim_game g on g.game_sk = f.game_sk
        join core.review_text t on t.review_sk = f.review_sk
        join core.dim_language l on l.language_sk = f.language_sk
        where {" and ".join(conds)}
        order by {order}
        limit %(limit)s offset %(offset)s
    """, {"app": app_id, "since": since, "until": until, "up": vote == "up", "language": language,
          "limit": REVIEWS_PAGE + 1, "offset": offset,
          # % и _ в слове - буквы, а не шаблон ilike
          "text": "%" + re.sub(r"([%_\\])", r"\\\1", text or "") + "%"})
    return {"items": rows[:REVIEWS_PAGE], "more": len(rows) > REVIEWS_PAGE}


def digest(app_id):
    """Сводки месяца от модели, свежие первыми; пустой список - игра не размечается или сводок ещё нет."""
    return query("""
        select period_from, period_to, headline, summary
        from marts.game_digest_current
        where app_id = %s and checks_passed
        order by period_from desc
    """, (app_id,))


@lru_cache(maxsize=512)
def words(app_id, since, until, vote):
    """Слова, которые в отзывах за [since, until) встречаются чаще, чем за 90 дней до since. Без модели, средствами Postgres.

    Считается доля отзывов со словом (каждый отзыв - один голос), рост - отношение долей со сглаживанием на единицу.
    Слова берутся как есть, без приведения к основе: основа вроде «balanc» читателю непонятна. Стоп-слова отсекаются
    словарями английского и русского; отзывы на других языках не участвуют - для них нет словарей.
    Кэш на процесс: ответ для прошедших дат не меняется, а новые даты дают новый ключ.
    """
    rows = query("""
        with docs as (
            select f.created_at >= %(since)s as recent, to_tsvector('simple', t.review_body) as v
            from core.fct_review f
            join core.dim_game g on g.game_sk = f.game_sk
            join core.review_text t on t.review_sk = f.review_sk
            join core.dim_language l on l.language_sk = f.language_sk
            where g.app_id = %(app)s and f.created_at >= %(base)s and f.created_at < %(until)s
              and f.is_voted_up = %(up)s and l.language_code in ('english', 'russian')
        ),
        n as (select count(*) filter (where recent) as recent, count(*) filter (where not recent) as base from docs),
        w as (
            select w, count(*) filter (where recent) as recent, count(*) filter (where not recent) as base
            from docs, unnest(tsvector_to_array(v)) as w
            where length(w) > 2 and w !~ '^[0-9]+$'
            group by w
        )
        -- lateral, чтобы число отзывов пришло и тогда, когда ни одно слово не прошло порог
        select n.recent as total, x.*
        from n
        left join lateral (
            select w.w as word, w.recent as reviews,
                   round(100.0 * w.recent / nullif(n.recent, 0), 1) as share,
                   round(((w.recent + 1.0) / (n.recent + 1)) / ((w.base + 1.0) / (n.base + 1)), 2) as lift
            from w
            where w.recent >= greatest(5, n.recent / 100) and w.w <> all(%(common)s)
              and length(to_tsvector('english', w.w)) > 0 and length(to_tsvector('russian', w.w)) > 0
        ) x on true
    """, {"app": app_id, "since": since, "until": until, "base": since - timedelta(days=WORDS_BASE_DAYS), "up": vote == "up",
          "common": COMMON_WORDS})
    total = rows[0]["total"] if rows else 0
    rows = [r for r in rows if r["word"] is not None]
    return {
        "reviews": total,
        # частые - о чём пишут вообще, растущие - что изменилось: разные вопросы, поэтому два списка
        "top": sorted(rows, key=lambda r: -r["reviews"])[:WORDS],
        "rising": [r for r in sorted(rows, key=lambda r: -r["lift"]) if r["lift"] >= 1.3][:WORDS],
    }


def lengths(app_id):
    """Медианная длина текста отзыва за 90 дней: рекомендующие и нет. Недовольные обычно пишут длиннее - и это видно."""
    rows = query("""
        select f.is_voted_up as up, percentile_cont(0.5) within group (order by char_length(t.review_body))::int as median
        from core.fct_review f
        join core.dim_game g on g.game_sk = f.game_sk
        join core.review_text t on t.review_sk = f.review_sk
        where g.app_id = %s and f.created_at >= (select max(created_at) from core.fct_review f2
                                                 join core.dim_game g2 on g2.game_sk = f2.game_sk where g2.app_id = %s) - interval '90 days'
          and char_length(btrim(coalesce(t.review_body, ''))) >= 20
        group by f.is_voted_up
    """, (app_id, app_id))
    return {"up" if r["up"] else "down": r["median"] for r in rows}
