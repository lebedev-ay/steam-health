"""Выводы по точкам перелома: короткий текст из двух частей по уликам из витрин разметки.

    python -m llm.verdict --app-id 892970 [--dry-run]

Точки - детектор дашборда (collector/change_points.py), не больше MAX_POINTS самых сильных на игру.
Для каждой точки собираются улики и их хэш: хэш не изменился - вывод не пересчитывается. Решения (направление, характер,
новости, объём, значимость) принимает код, формулировки - модель. Незначимое изменение главной темы - шаблон без модели.
Ответ не прошёл проверки кодом - один повтор; не прошёл снова - сохраняется с замечаниями, дашборд такой текст не показывает.
"""

import argparse
import math
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from llm import client, codebook
from llm.verdict_check import WINDOW, check, evidence_hash, excerpts, percent, refs, status

# детектор и DSN общие с collector/, а он не пакет - подключается так же, как в tools/
sys.path.insert(0, str(Path(__file__).parent.parent / "collector"))

import change_points
from db import DSN

PROMPT_NAME = "verdict-v5"
PROMPT = Path(__file__).parent / "prompts" / "verdict_v5.txt"
PARAMS = {k: client.GENERATION[k] for k in ("temperature", "max_tokens", "reasoning")}

MAX_POINTS = 10
TOP = 3
FOCUSED = 0.5                # главная тема несёт не меньше половины изменения
SIGNIFICANT_SE = 2           # изменение главной темы меньше двух стандартных ошибок разности - вывод пишет шаблон
SMALL_VOLUME = 10            # меньше отзывов с жалобами на главную тему - объём малый
REVIEWS_PER_CATEGORY = 15
REVIEW_CHARS = 300
PLAYTIME = [("до 10 ч", 0, 600), ("10-100 ч", 600, 6000), ("100+ ч", 6000, None)]
SERVICE = ("overall", "other")
OUTPUT_TOKENS = 350          # оценка выхода на вывод для --dry-run; на прогоне v5 - 240 в среднем
VOTES = "доля отзывов с оценкой «не рекомендую»"
COMPLAINTS = "доля отзывов с жалобами в тексте"


def r6(x):
    # 6 знаков, а не 4: округление до 0.025 превращало 0.02502 в 2% вместо 3%
    return None if x is None else round(x, 6)


# =============================================================================
# Точки
# =============================================================================

def points(app_id):
    smoothed, raw_daily, _, _ = change_points.build_series(app_id, "auto")
    if not raw_daily:
        return []
    found, _ = change_points.find_change_points(smoothed)
    found = sorted(found, key=lambda t: -abs(t[1]))[:MAX_POINTS]
    cp_events, _, platform_events, _ = change_points.build_events(app_id, raw_daily, 0)
    out = []
    for idx, score in sorted(found):
        day = date.fromisoformat(smoothed[idx]["day"])
        near = change_points.attach_events([(idx, score)], smoothed, cp_events, platform_events)[0]
        news = []
        for major, items in ((True, near["events"]), (False, near["events_minor"])):
            for e in items:
                # attach_events дату новости не отдаёт, а без неё модель приписывает новости дату точки
                day_of = min((c["day"] for c in cp_events if c["title"] == e["title"] and abs((c["day"] - day).days) <= 3),
                             key=lambda d: abs((d - day).days), default=None)
                news.append({"date": day_of and day_of.isoformat(), "title": e["title"], "type": e["type"],
                             "weight": r6(e.get("weight")), "major": major})
        out.append({"day": day, "shift_pp": round(score, 1), "news": news, "platform_event": near["platform_event"]})
    return out


# =============================================================================
# Улики из витрин
# =============================================================================

def load_marts(conn, app_id, cfg_sk, codebook_version):
    days = conn.execute("""
        select day, content_count, labeled_count from marts.review_labeling_daily
        where app_id = %s and llm_config_sk = %s order by day
    """, (app_id, cfg_sk)).fetchall()
    cats = conn.execute("""
        select day, category_id as key, negative_count + mixed_count as critique from marts.review_category_daily
        where app_id = %s and llm_config_sk = %s
    """, (app_id, cfg_sk)).fetchall()
    aspects = conn.execute("""
        select day, category_id, aspect_id as key, negative_count + mixed_count as critique from marts.review_aspect_daily
        where app_id = %s and llm_config_sk = %s
    """, (app_id, cfg_sk)).fetchall()
    names = {r["category_id"]: r["category_name"] for r in conn.execute(
        "select distinct category_id, category_name from core.dim_aspect where codebook_version = %s", (codebook_version,))}
    return days, cats, aspects, names


def by_key(rows):
    out = defaultdict(dict)
    for r in rows:
        out[r["key"]][r["day"]] = out[r["key"]].get(r["day"], 0) + r["critique"]
    return out


def weighted_share(days, critique, lo, hi):
    """(доля, размечено, отзывов с жалобами) за [lo, hi): среднее дневных долей с весом числа отзывов с текстом, как в explore/llm/viz."""
    num = den = labeled = crit = 0
    for d in days:
        if d["labeled_count"] == 0 or d["day"] < lo or d["day"] >= hi:
            continue
        n = critique.get(d["day"], 0)
        num += d["content_count"] * n / d["labeled_count"]
        den += d["content_count"]
        labeled += d["labeled_count"]
        crit += n
    return (num / den if den else None), labeled, crit


def before_after(days, crit, keys, at):
    lo, hi = at - timedelta(days=WINDOW), at + timedelta(days=WINDOW)
    rows = []
    for k in keys:
        b, lb, nb = weighted_share(days, crit.get(k, {}), lo, at)
        a, la, na = weighted_share(days, crit.get(k, {}), at, hi)
        if b is None or a is None:
            continue
        rows.append({"key": k, "before": r6(b), "after": r6(a), "diff": r6(a - b), "crit_before": nb, "crit_after": na,
                     "labeled_before": lb, "labeled_after": la})
    return sorted(rows, key=lambda r: -r["diff"])


def votes(conn, app_id, at):
    rows = conn.execute("""
        select day >= %(at)s as after, sum(review_count)::bigint as n, sum(review_count - positive_count)::bigint as neg
        from marts.review_daily where app_id = %(app)s and day >= %(lo)s and day < %(hi)s group by 1
    """, {"app": app_id, "at": at, "lo": at - timedelta(days=WINDOW), "hi": at + timedelta(days=WINDOW)}).fetchall()
    by = {r["after"]: r for r in rows}
    return {side: {"reviews": int(by[flag]["n"]) if flag in by else 0,
                   "negative_share": r6(by[flag]["neg"] / by[flag]["n"]) if flag in by and by[flag]["n"] else None}
            for side, flag in (("before", False), ("after", True))}


def playtime(conn, app_id, cfg_sk, category, at):
    rows = conn.execute("""
        with crit as (
            select labeling_sk from marts.review_aspect_tag
            where app_id = %(app)s and llm_config_sk = %(cfg)s and category_id = %(cat)s
            group by labeling_sk having bool_or(sentiment in ('-', '±'))
        )
        select r.day >= %(at)s as after, f.playtime_at_review_min as minutes, c.labeling_sk is not null as critical
        from marts.review_labeled r
        join core.fct_review f on f.recommendation_id = r.recommendation_id
        left join crit c on c.labeling_sk = r.labeling_sk
        where r.app_id = %(app)s and r.llm_config_sk = %(cfg)s and r.day >= %(lo)s and r.day < %(hi)s
    """, {"app": app_id, "cfg": cfg_sk, "cat": category, "at": at,
          "lo": at - timedelta(days=WINDOW), "hi": at + timedelta(days=WINDOW)}).fetchall()
    out = []
    for name, lo, hi in PLAYTIME:
        group = {"group": name}
        for side, flag in (("before", False), ("after", True)):
            sel = [r for r in rows if r["after"] == flag and r["minutes"] is not None
                   and r["minutes"] >= lo and (hi is None or r["minutes"] < hi)]
            crit = sum(r["critical"] for r in sel)
            group[side] = {"labeled": len(sel), "share": r6(crit / len(sel)) if sel else None}
        out.append(group)
    return out


def support_reviews(conn, app_id, cfg_sk, category, at, signs):
    """Отзывы окна «после» со знаком по направлению точки: половина - по votes_up, половина - воспроизводимо случайные."""
    rows = conn.execute("""
        with cat as (
            select labeling_sk, case when min(sentiment) = max(sentiment) then min(sentiment) else '±' end as sentiment
            from marts.review_aspect_tag
            where app_id = %(app)s and llm_config_sk = %(cfg)s and category_id = %(cat)s and day >= %(lo)s and day < %(hi)s
            group by labeling_sk
        )
        select r.recommendation_id, f.votes_up, left(v.review_body, %(n)s) as text, char_length(v.review_body) as length,
               md5(r.recommendation_id::text || %(lo)s::text) as h
        from cat c
        join marts.review_labeled r on r.labeling_sk = c.labeling_sk
        join core.fct_review f on f.recommendation_id = r.recommendation_id
        join core.fct_review_labeling l on l.labeling_sk = c.labeling_sk
        join core.review_text_version v on v.review_text_sk = l.review_text_sk
        where c.sentiment = any(%(signs)s)
    """, {"app": app_id, "cfg": cfg_sk, "cat": category, "lo": at, "hi": at + timedelta(days=WINDOW),
          "n": REVIEW_CHARS, "signs": list(signs)}).fetchall()
    top = sorted(rows, key=lambda r: (-r["votes_up"], r["recommendation_id"]))[:(REVIEWS_PER_CATEGORY + 1) // 2]
    taken = {r["recommendation_id"] for r in top}
    rest = sorted((r for r in rows if r["recommendation_id"] not in taken), key=lambda r: r["h"])
    return top + rest[:REVIEWS_PER_CATEGORY - len(top)]


def labels(v, categories):
    """Решения кодом: направление, характер (со значимостью главной темы), главная тема, объём."""
    dv = (v["after"]["negative_share"] or 0) - (v["before"]["negative_share"] or 0)
    net = sum(r["diff"] for r in categories)
    direction = "ухудшение" if dv > 0 and net > 0 else "улучшение" if dv < 0 and net < 0 else "смешанное"
    up = net >= 0
    total = sum(r["diff"] for r in categories if r["diff"] != 0 and (r["diff"] > 0) == up)
    ranked = sorted(categories, key=lambda r: -r["diff"] if up else r["diff"])
    main = ranked[0] if ranked and ranked[0]["diff"] != 0 and (ranked[0]["diff"] > 0) == up else None
    se = None
    if main and main["labeled_before"] and main["labeled_after"]:
        b, a = main["before"], main["after"]
        se = math.sqrt(b * (1 - b) / main["labeled_before"] + a * (1 - a) / main["labeled_after"])
    significant = bool(main) and se is not None and abs(main["diff"]) >= SIGNIFICANT_SE * se
    focus = main["diff"] / total if significant and total else None
    return {
        "direction": direction,
        "character": "не определён" if not significant else "сфокусированный" if focus >= FOCUSED else "размазанный",
        "critique_up": up, "focus": r6(focus), "se": r6(se), "significant": significant,
        "main": main and main["key"],
        "volume": main and ("малый" if max(main["crit_before"], main["crit_after"]) < SMALL_VOLUME else "достаточный"),
    }


def evidence(conn, app_id, point, cfg, marts):
    days, cats, aspects, names = marts
    at = point["day"]
    crit = by_key(cats)
    rows = [{**r, "name": names.get(r["key"], r["key"])}
            for r in before_after(days, crit, sorted(k for k in crit if k not in SERVICE), at)]
    v = votes(conn, app_id, at)
    lab = labels(v, rows)
    lab["news"] = "есть" if point["news"] else "нет"
    ev = {
        "app_id": app_id, "change_date": at.isoformat(),
        "before_from": (at - timedelta(days=WINDOW)).isoformat(), "after_to": (at + timedelta(days=WINDOW)).isoformat(),
        # смена конфигурации разметки меняет хэш улик и даёт новый вывод даже при совпадающих числах
        "labeling_config_sk": cfg["llm_config_sk"],
        "news": point["news"], "platform_event": point["platform_event"],
        "votes": v, "labels": lab,
        "rising": [r for r in rows if r["diff"] > 0][:TOP] if lab["direction"] != "улучшение" else [],
        "falling": sorted((r for r in rows if r["diff"] < 0), key=lambda r: r["diff"])[:TOP] if lab["direction"] != "ухудшение" else [],
        "subaspects": [], "playtime": [], "review_kind": None, "review_blocks": [], "reviews": [],
    }
    main = next((r for r in rows if r["key"] == lab["main"]), None)
    ev["main"] = main
    if main and lab["significant"]:
        acrit = by_key([a for a in aspects if a["category_id"] == main["key"]])
        ev["subaspects"] = sorted(before_after(days, acrit, sorted(acrit), at),
                                  key=lambda r: -r["diff"] if lab["critique_up"] else r["diff"])
        ev["playtime"] = playtime(conn, app_id, cfg["llm_config_sk"], main["key"], at)
        ev["review_kind"] = "жалобы" if lab["critique_up"] else "похвала"
        signs = ("-", "±") if lab["critique_up"] else ("+",)
        numbers = {}
        for cat in (ev["rising"] if lab["critique_up"] else ev["falling"]):
            block = []
            for r in support_reviews(conn, app_id, cfg["llm_config_sk"], cat["key"], at, signs):
                if r["recommendation_id"] not in numbers:
                    numbers[r["recommendation_id"]] = len(numbers) + 1
                    ev["reviews"].append({"number": numbers[r["recommendation_id"]], "recommendation_id": r["recommendation_id"],
                                          "votes_up": r["votes_up"],
                                          "text": r["text"] + ("…" if r["length"] > REVIEW_CHARS else "")})
                block.append(numbers[r["recommendation_id"]])
            ev["review_blocks"].append({"name": cat["name"], "numbers": block})
    return ev


# =============================================================================
# Текст улик для модели и шаблон
# =============================================================================

def pct(x):
    return "нет данных" if x is None else f"{percent(x)}%"


def pp(x):
    return f"{'-' if x < 0 else '+'}{percent(abs(x))} п.п."


def news_line(e):
    day = date.fromisoformat(e["date"]).strftime("%d.%m.%Y") if e["date"] else "дата неизвестна"
    kind = f"вес {e['weight']:.1f}" if e["major"] and e["weight"] is not None else "фоновое"
    return f"{day}: «{e['title']}» (тип {e['type']}, {kind})"


def as_text(game, ev):
    lab, v, main = ev["labels"], ev["votes"], ev["main"]
    lines = [
        f"Игра: {game}. Дата: {ev['change_date']}. Окна: 7 дней до и 7 дней после, день даты входит в окно после.",
        "ЯРЛЫКИ (обязательны к исполнению):",
        f"- направление: {lab['direction']}",
        f"- характер: {lab['character']}" + (f" (главная категория несёт {pct(lab['focus'])} изменения)" if lab["focus"] is not None else ""),
        f"- новости: {lab['news']}",
        f"- объём: {lab['volume']}",
        "Новости игры в пределах 3 дней: " + ("; ".join(news_line(e) for e in ev["news"]) or "нет"),
    ]
    if ev["platform_event"]:
        pe = ev["platform_event"]
        lines.append(f"Событие платформы Steam рядом (не новость игры): {pe['title']} ({pe['type']})")
    lines.append(f"Отзывов за 7 дней: до {v['before']['reviews']}, после {v['after']['reviews']}.")
    lines.append(f"Метрика 1 - {VOTES} (все отзывы): до {pct(v['before']['negative_share'])}, после {pct(v['after']['negative_share'])}.")
    for title, rows in (("наибольший рост", ev["rising"]), ("наибольшее падение", ev["falling"])):
        if rows:
            lines.append(f"Метрика 2 - {COMPLAINTS} (по разметке, среди отзывов с текстом), категории - {title}:")
            lines += [f"- {r['name']}: до {pct(r['before'])}, после {pct(r['after'])}, изменение {pp(r['diff'])}; "
                      f"отзывов с жалобами до {r['crit_before']}, после {r['crit_after']}" for r in rows]
    lines.append(f"Главная категория: {main['name']}, изменение {pp(main['diff'])}")
    lines.append(f"Значимость изменения главной категории: разница {pp(main['diff'])}, стандартная ошибка разности "
                 f"{lab['se'] * 100:.1f} п.п., порог {SIGNIFICANT_SE} ст. ошибки - значимо")
    lines.append(f"Подаспекты главной категории {main['name']} ({COMPLAINTS}):")
    lines += [f"- {r['key']}: до {pct(r['before'])}, после {pct(r['after'])}, изменение {pp(r['diff'])}, "
              f"отзывов с жалобами до {r['crit_before']}, после {r['crit_after']}" for r in ev["subaspects"]]
    lines.append(f"Доля отзывов с жалобами на {main['name']} по наигранному времени (среди размеченных, без взвешивания):")
    lines += [f"- {g['group']}: до {pct(g['before']['share'])} из {g['before']['labeled']}, "
              f"после {pct(g['after']['share'])} из {g['after']['labeled']}" for g in ev["playtime"]]
    if lab["volume"] == "малый":
        lines.append(f"Отзывов с жалобами на главную категорию: до {main['crit_before']}, после {main['crit_after']}.")
    kind = "с жалобами" if ev["review_kind"] == "жалобы" else "с похвалой"
    lines.append(f"ОТЗЫВЫ-ОПОРЫ: отзывы из окна после {kind} по главным категориям, первые {REVIEW_CHARS} символов. "
                 "Ссылаться в what_players_say по номерам в квадратных скобках.")
    reviews = {r["number"]: r for r in ev["reviews"]}
    shown = set()
    for block in ev["review_blocks"]:
        lines.append(f"Категория {block['name']}:")
        for n in block["numbers"]:
            if n not in shown:
                shown.add(n)
                lines.append(f"[{n}] (полезно: {reviews[n]['votes_up']}) «{reviews[n]['text']}»")
    return "\n".join(lines)


def template(ev):
    v = ev["votes"]
    b, a = v["before"]["negative_share"], v["after"]["negative_share"]
    change = "" if a is None or b is None else f" ({pp(a - b)})"
    return (f"Доля отзывов с оценкой «не рекомендую» - {pct(b)} за 7 дней до и {pct(a)} после{change}; "
            "ни одна категория разметки не изменилась значимо.")


# =============================================================================
# Генерация и запись
# =============================================================================

def generate(prompt, text, ev, vocab, price):
    """Вызов модели с одним повтором при непрошедшей проверке. Вернуть (замечания, what, talk, попыток, расход)."""
    reviews = {r["number"] for r in ev["reviews"]}
    lab = {**ev["labels"], "main_diff": ev["main"]["diff"]}
    v = ev["votes"]
    votes_pair = (None if v["before"]["negative_share"] is None or v["after"]["negative_share"] is None
                  else (percent(v["before"]["negative_share"]), percent(v["after"]["negative_share"])))
    spend = {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost": 0.0}
    for attempt in (1, 2):
        raw, finish, usage = client.complete(prompt, text)
        for key, n in zip(("input", "cached", "output"), client.tokens(usage)):
            spend[key] += n
        spend["reasoning"] += client.reasoning_tokens(usage)
        c = client.cost(usage, price)
        spend["cost"] = None if c is None or spend["cost"] is None else spend["cost"] + c
        problems, what, talk = check(raw, lab, votes_pair, reviews, vocab)
        if finish != "stop":
            problems.append(f"ответ обрезан: {finish}")
        if not problems:
            break
        print(f"  попытка {attempt}: {problems}")
    return problems, what or raw, talk, attempt, spend


def review_languages(conn, reviews):
    """{номер опоры: код языка}. Язык берётся из core.fct_review при выборе отрывков и в улики не входит - хэш от него не зависит."""
    ids = {r["recommendation_id"]: r["number"] for r in reviews}
    rows = conn.execute("""
        select f.recommendation_id, l.language_code
        from core.fct_review f join core.dim_language l on l.language_sk = f.language_sk
        where f.recommendation_id = any(%s)
    """, (list(ids),)).fetchall()
    return {ids[r["recommendation_id"]]: r["language_code"] for r in rows}


def save(conn, ev, h, point, cfg_sk, author, what, talk, problems, attempts, spend, run_id, today):
    reviews = {r["number"]: r for r in ev["reviews"]}
    support = sorted(set(refs(talk or "")) & set(reviews))
    conn.execute("""
        insert into core.fct_change_point_verdict (
            app_id, change_date, before_from, after_to, llm_config_sk, labeling_config_sk, evidence, evidence_hash,
            detector_shift_pp, author, what_happened, what_players_say, support_numbers, excerpts, checks, checks_passed,
            attempts, status, run_id, input_tokens, cached_tokens, output_tokens, reasoning_tokens, cost_usd)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (ev["app_id"], ev["change_date"], ev["before_from"], ev["after_to"], cfg_sk, ev["labeling_config_sk"],
          Jsonb(ev), h, point["shift_pp"], author, what, talk, support,
          Jsonb(excerpts(support, reviews, review_languages(conn, ev["reviews"]))), Jsonb(problems), not problems, attempts, status(point["day"], today), run_id,
          spend["input"], spend["cached"], spend["output"], spend["reasoning"], spend["cost"]))
    conn.commit()


def estimate(prompt, text, price):
    if price is None:
        return None
    n_in = len(prompt) / client.PROMPT_CHARS_PER_TOKEN + len(text) / client.TEXT_CHARS_PER_TOKEN
    return client.price_of(n_in, 0, OUTPUT_TOKENS, price)


def main():
    parser = argparse.ArgumentParser(description="Выводы по точкам перелома")
    parser.add_argument("--app-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true", help="посчитать точки, новые и изменившиеся, и цену - без модели и записи")
    args = parser.parse_args()

    _, model = client.settings()
    if not args.dry_run:
        client.api_key()   # без ключа выход до любой записи в базу
    prompt = PROMPT.read_text(encoding="utf-8").strip()
    price = client.prices()
    today = datetime.now(timezone.utc).date()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-v{args.app_id}"

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        cfg = conn.execute("select llm_config_sk, codebook_version from marts.llm_config_active").fetchone()
        if cfg is None:
            raise SystemExit("нет активной конфигурации разметки в marts.llm_config_active")
        if args.dry_run:
            cfg_sk = codebook.find_config(conn, model, prompt, PARAMS)
        else:
            cfg_sk = codebook.ensure_config(conn, model, prompt, PARAMS, cfg["codebook_version"], PROMPT_NAME)
            conn.commit()
        game = conn.execute("select game_name from marts.dim_game_current where app_id = %s", (args.app_id,)).fetchone()
        game = game["game_name"] if game else str(args.app_id)
        vocab = sorted({x for r in conn.execute(
            "select aspect_id, aspect_name, category_id, category_name from core.dim_aspect where codebook_version = %s",
            (cfg["codebook_version"],)) for x in r.values()} - {"other", "Other", "overall", "Overall"}, key=len, reverse=True)
        marts = load_marts(conn, args.app_id, cfg["llm_config_sk"], cfg["codebook_version"])

        counts = {"new": 0, "changed": 0, "same": 0, "finalized": 0, "excerpts": 0, "model": 0, "template": 0, "flagged": 0}
        spend_total = {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost": 0.0}
        est_total = 0.0
        started = time.monotonic()
        pts = points(args.app_id)
        print(f"{game}: точек детектора {len(pts)} | промпт {PROMPT_NAME} ({codebook.prompt_hash(prompt)[:8]}) | {model}")

        for point in pts:
            ev = evidence(conn, args.app_id, point, cfg, marts)
            h = evidence_hash(ev)
            existing = conn.execute("""
                select verdict_sk, evidence_hash, status, support_numbers, excerpts, evidence -> 'reviews' as reviews
                from core.fct_change_point_verdict
                where app_id = %s and change_date = %s and llm_config_sk = %s order by created_at desc
            """, (args.app_id, point["day"], cfg_sk)).fetchall() if cfg_sk else []
            same = next((r for r in existing if r["evidence_hash"] == h), None)
            if same:
                counts["same"] += 1
                # улики не изменились, а окно «после» уже закрыто - вывод становится итоговым без генерации
                if same["status"] == "preliminary" and status(point["day"], today) == "final" and not args.dry_run:
                    conn.execute("update core.fct_change_point_verdict set status = 'final' where verdict_sk = %s",
                                 (same["verdict_sk"],))
                    conn.commit()
                    counts["finalized"] += 1
                # отрывки - представление вывода, а не его улики: при смене правила отбора обновляются без генерации
                fresh = excerpts(same["support_numbers"], {r["number"]: r for r in same["reviews"]},
                                 review_languages(conn, same["reviews"]))
                if fresh != same["excerpts"] and not args.dry_run:
                    conn.execute("update core.fct_change_point_verdict set excerpts = %s where verdict_sk = %s",
                                 (Jsonb(fresh), same["verdict_sk"]))
                    conn.commit()
                    counts["excerpts"] += 1
                continue
            counts["changed" if existing else "new"] += 1
            templated = not ev["labels"]["significant"]
            text = None if templated else as_text(game, ev)
            if args.dry_run:
                if text:
                    e = estimate(prompt, text, price)
                    est_total = None if e is None or est_total is None else est_total + e
                print(f"  {point['day']}: {'изменились улики' if existing else 'новая'}, {'шаблон' if templated else 'модель'}")
                continue

            if templated:
                problems, what, talk, attempts = [], template(ev), None, 1
                spend = {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost": 0.0}
                counts["template"] += 1
            else:
                problems, what, talk, attempts, spend = generate(prompt, text, ev, vocab, price)
                counts["model"] += 1
                counts["flagged"] += bool(problems)
            save(conn, ev, h, point, cfg_sk, "template" if templated else "model", what, talk, problems, attempts,
                 spend, run_id, today)
            for key in ("input", "cached", "output", "reasoning"):
                spend_total[key] += spend[key]
            spend_total["cost"] = None if spend["cost"] is None or spend_total["cost"] is None else spend_total["cost"] + spend["cost"]
            print(f"  {point['day']}: {'шаблон' if templated else 'модель'}{', замечания: ' + str(problems) if problems else ''}")

    print(f"новых {counts['new']}, изменившихся {counts['changed']}, без изменений {counts['same']}"
          + (f" (переведено в итоговые {counts['finalized']})" if counts["finalized"] else "")
          + (f", обновлены отрывки {counts['excerpts']}" if counts["excerpts"] else ""))
    if args.dry_run:
        print(f"оценка: {'цена неизвестна' if est_total is None else f'${est_total:.4f}'}")
        return
    cost = "цена неизвестна" if spend_total["cost"] is None else f"${spend_total['cost']:.4f}"
    print(f"run_id {run_id} | {time.monotonic() - started:.0f} с | модель {counts['model']} (не прошли проверки {counts['flagged']}), "
          f"шаблон {counts['template']} | {cost} | токены вход {spend_total['input']} (кэш {spend_total['cached']}), "
          f"выход {spend_total['output']} (размышления {spend_total['reasoning']})")


if __name__ == "__main__":
    main()
