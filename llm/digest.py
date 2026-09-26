"""Сводка месяца по игре: заголовок и 2-3 фразы от модели по числам витрин разметки.

    python -m llm.digest --app-id 892970 [--months 3] [--dry-run]
    python -m llm.digest --all-enabled [--months 3] [--dry-run]      - все игры, включённые в core.llm_game

Берутся последние --months завершённых месяцев с разметкой. Модель видит только агрегаты - доли оценок, доли жалоб и похвалы
по темам, новые темы, новости и переломы месяца - и ни одного текста отзыва, поэтому вызов стоит порядка тысячи токенов.
Улики не изменились (хэш) - сводка не пересчитывается. Ответ проверяется кодом: не прошёл - один повтор, затем сохраняется
с замечаниями, и дашборд его не показывает.
"""

import argparse
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from llm import client, codebook
from llm.verdict_check import SNAKE, evidence_hash, foreign_letters, percent

from db import DSN

PROMPT_NAME = "digest-v1"
PROMPT = Path(__file__).parent / "prompts" / "digest_v1.txt"
PARAMS = {k: client.GENERATION[k] for k in ("temperature", "max_tokens", "reasoning")}
OUTPUT_TOKENS = 200          # оценка выхода для --dry-run
TOP = 5
HEADLINE_CHARS = 90
SUMMARY_WORDS = 80
PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
CAUSAL = re.compile(r"из-за|вызвал|привел\w*\s+к|привёл\s+к|в\s+ответ\s+на|спровоцир|стал\w*\s+причин", re.I)


# =============================================================================
# Улики
# =============================================================================

def months_to_digest(conn, app_id, cfg_sk, n):
    """Последние n завершённых месяцев, в которых игра размечалась."""
    rows = conn.execute("""
        select distinct date_trunc('month', day)::date as month
        from marts.review_labeling_daily
        where app_id = %s and llm_config_sk = %s and labeled_count > 0
          and day < date_trunc('month', current_date)
        order by 1 desc limit %s
    """, (app_id, cfg_sk, n)).fetchall()
    return sorted(r["month"] for r in rows)


def next_month(m):
    return date(m.year + m.month // 12, m.month % 12 + 1, 1)


def prev_month(m):
    return date(m.year - (m.month == 1), (m.month - 2) % 12 + 1, 1)


def month_numbers(conn, app_id, cfg_sk, month):
    """Доли за месяц: оценки всех отзывов, жалобы и похвала по категориям и темам среди размеченных."""
    lo, hi = month, next_month(month)
    votes = conn.execute("""
        select coalesce(sum(review_count), 0)::int as reviews, coalesce(sum(positive_count), 0)::int as positive
        from marts.review_daily where app_id = %s and day >= %s and day < %s
    """, (app_id, lo, hi)).fetchone()
    labeled = conn.execute("""
        select coalesce(sum(labeled_count), 0)::int as n from marts.review_labeling_daily
        where app_id = %s and llm_config_sk = %s and day >= %s and day < %s
    """, (app_id, cfg_sk, lo, hi)).fetchone()["n"]

    def shares(table, key, exclude):
        rows = conn.execute(f"""
            select {key} as key, sum(negative_count + mixed_count)::int as critique, sum(positive_count)::int as praise
            from marts.{table}
            where app_id = %s and llm_config_sk = %s and day >= %s and day < %s and {key} <> all(%s)
            group by 1
        """, (app_id, cfg_sk, lo, hi, exclude)).fetchall()
        return {r["key"]: {"critique": r["critique"] / labeled, "praise": r["praise"] / labeled} for r in rows} if labeled else {}

    return {
        "reviews": votes["reviews"],
        "positive_share": votes["positive"] / votes["reviews"] if votes["reviews"] else None,
        "labeled": labeled,
        "categories": shares("review_category_daily", "category_id", ["overall", "other"]),
        "aspects": shares("review_aspect_daily", "aspect_id", ["overall_impression", "other"]),
    }


def evidence(conn, app_id, cfg, month):
    cfg_sk = cfg["llm_config_sk"]
    now, prev = month_numbers(conn, app_id, cfg_sk, month), month_numbers(conn, app_id, cfg_sk, prev_month(month))
    names = {}
    for r in conn.execute("select category_id, category_name, aspect_id, aspect_name from core.dim_aspect where codebook_version = %s",
                          (cfg["codebook_version"],)):
        names[r["category_id"]], names[r["aspect_id"]] = r["category_name"], r["aspect_name"]

    def compare(key):
        rows = []
        for k in sorted(set(now[key]) | set(prev[key])):
            a, b = now[key].get(k, {"critique": 0, "praise": 0}), prev[key].get(k, {"critique": 0, "praise": 0})
            rows.append({"id": k, "name": names.get(k, k),
                         "critique": round(a["critique"], 6), "critique_prev": round(b["critique"], 6),
                         "praise": round(a["praise"], 6), "praise_prev": round(b["praise"], 6)})
        # самое заметное - наибольшее изменение жалоб или похвалы
        return sorted(rows, key=lambda r: -max(abs(r["critique"] - r["critique_prev"]), abs(r["praise"] - r["praise_prev"])))[:TOP]

    new_topics = conn.execute("""
        select t.note, count(*)::int as n
        from marts.review_labeled r
        join core.fct_review_aspect t on t.labeling_sk = r.labeling_sk
        join core.dim_aspect a on a.aspect_sk = t.aspect_sk and a.aspect_id = 'other'
        where r.app_id = %s and r.llm_config_sk = %s and r.day >= %s and r.day < %s
        group by 1 order by 2 desc, 1 limit %s
    """, (app_id, cfg_sk, month, next_month(month), TOP)).fetchall()
    news = conn.execute("""
        select distinct (p.published_at at time zone 'utc')::date as date, p.title, p.event_type as type, p.weight
        from core.fct_patch p join core.dim_game g on g.game_sk = p.game_sk
        where g.app_id = %s and p.published_at >= %s and p.published_at < %s
          and (p.event_type in ('season_start', 'expansion') or (p.event_type not in ('marketing', 'blog', 'service') and p.weight >= 2))
        order by p.weight desc nulls first, 1 limit %s
    """, (app_id, month, next_month(month), TOP)).fetchall()
    points = conn.execute("""
        select change_date as date, detector_shift_pp as shift_pp from marts.change_point_verdict_current
        where app_id = %s and change_date >= %s and change_date < %s order by 1
    """, (app_id, month, next_month(month))).fetchall()

    return {
        "app_id": app_id, "month": month.isoformat(), "labeling_config_sk": cfg_sk,
        "reviews": {"now": now["reviews"], "prev": prev["reviews"]},
        "positive_share": {"now": now["positive_share"] and round(now["positive_share"], 6),
                           "prev": prev["positive_share"] and round(prev["positive_share"], 6)},
        "labeled": {"now": now["labeled"], "prev": prev["labeled"]},
        "categories": compare("categories"),
        "aspects": compare("aspects"),
        "new_topics": new_topics,
        "news": [{**n, "date": n["date"].isoformat(), "weight": n["weight"] and float(n["weight"])} for n in news],
        "turning_points": [{"date": p["date"].isoformat(), "shift_pp": float(p["shift_pp"] or 0)} for p in points],
    }


# =============================================================================
# Текст для модели и проверка ответа - без базы, это и тестируется
# =============================================================================

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def pct(x):
    return "нет данных" if x is None else f"{percent(x)}%"


def as_text(game, ev):
    m = date.fromisoformat(ev["month"])
    p = ev["positive_share"]
    lines = [
        f"Игра: {game}. Месяц: {MONTHS[m.month - 1]} {m.year}, сравнение с предыдущим месяцем.",
        f"Отзывов: {ev['reviews']['now']} (в прошлом месяце {ev['reviews']['prev']}).",
        f"Доля положительных отзывов: {pct(p['now'])} (в прошлом месяце {pct(p['prev'])}).",
        f"Размечено отзывов с текстом: {ev['labeled']['now']} (в прошлом месяце {ev['labeled']['prev']}). "
        "Доли тем ниже - среди размеченных.",
    ]
    for title, key in (("Категории с наибольшим изменением:", "categories"), ("Темы с наибольшим изменением:", "aspects")):
        lines.append(title)
        lines += [f"- {r['id']} ({r['name']}): жалобы {pct(r['critique'])}, в прошлом месяце {pct(r['critique_prev'])}; "
                  f"похвала {pct(r['praise'])}, в прошлом месяце {pct(r['praise_prev'])}" for r in ev[key]]
    if ev["new_topics"]:
        lines.append("Новые темы вне справочника (слова игроков, число отзывов): "
                     + "; ".join(f"{t['note']} - {t['n']}" for t in ev["new_topics"]))
    lines.append("Новости игры за месяц: " + ("; ".join(f"{n['date']}: «{n['title']}» ({n['type']})" for n in ev["news"]) or "нет"))
    lines.append("Переломы доли позитива за месяц: "
                 + ("; ".join(f"{t['date']}: {'+' if t['shift_pp'] > 0 else ''}{t['shift_pp']} п.п." for t in ev["turning_points"]) or "нет"))
    return "\n".join(lines)


def known_numbers(ev):
    """Целые проценты, которые модель может назвать: всё, что показано в уликах, и разницы между месяцами."""
    shares = [ev["positive_share"]["now"], ev["positive_share"]["prev"]]
    for r in ev["categories"] + ev["aspects"]:
        shares += [r["critique"], r["critique_prev"], r["praise"], r["praise_prev"]]
    whole = {percent(s) for s in shares if s is not None}
    pairs = [(ev["positive_share"]["now"], ev["positive_share"]["prev"])] + \
            [(r[k], r[k + "_prev"]) for r in ev["categories"] + ev["aspects"] for k in ("critique", "praise")]
    diffs = {abs(percent(a) - percent(b)) for a, b in pairs if a is not None and b is not None}
    return whole | diffs


def parse(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict) or not all(isinstance(data.get(f), str) and data[f].strip() for f in ("headline", "summary")):
        return None, None
    return data["headline"].strip(), data["summary"].strip()


def check(raw, ev, vocab):
    """Замечания к ответу модели; пусто - сводку можно показывать. Вернуть (замечания, заголовок, текст)."""
    headline, summary = parse(raw)
    if headline is None:
        return ["не JSON с полями headline и summary"], None, None
    problems = []
    if len(headline) > HEADLINE_CHARS:
        problems.append(f"заголовок длиннее {HEADLINE_CHARS} символов")
    if len(summary.split()) > SUMMARY_WORDS:
        problems.append(f"текст длиннее {SUMMARY_WORDS} слов")
    both = f"{headline} {summary}"
    known = known_numbers(ev)
    for m in PERCENT.finditer(both):
        value = float(m.group(1).replace(",", "."))
        if value != int(value) or int(value) not in known:
            problems.append(f"число не из улик «{m.group(0)}»")
    for m in CAUSAL.finditer(both):
        problems.append(f"формулировка причины «{m.group(0)}»")
    letters = foreign_letters(both)
    if letters:
        problems.append(f"буквы не кириллицы и не латиницы «{''.join(letters)}»")
    for m in SNAKE.finditer(both):
        problems.append(f"id справочника «{m.group(0)}»")
    for name in vocab:
        if re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", both.lower()):
            problems.append(f"английское название «{name}»")
    return problems, headline, summary


# =============================================================================
# Генерация и запись
# =============================================================================

def generate(prompt, text, ev, vocab, price):
    spend = client.new_spend()
    for attempt in (1, 2):
        raw, finish, usage = client.complete(prompt, text)
        client.add_spend(spend, client.spend_of(usage, price))
        problems, headline, summary = check(raw, ev, vocab)
        if finish != "stop":
            problems.append(f"ответ обрезан: {finish}")
        if not problems:
            break
        print(f"  попытка {attempt}: {problems}")
    return problems, headline or "", summary or raw or "", attempt, spend


def process_game(conn, app_id, ctx, counts):
    game = conn.execute("select game_name from marts.dim_game_current where app_id = %s", (app_id,)).fetchone()
    game = game["game_name"] if game else str(app_id)
    months = months_to_digest(conn, app_id, ctx["cfg"]["llm_config_sk"], ctx["months"])
    print(f"{game}: месяцев {len(months)}")
    for month in months:
        ev = evidence(conn, app_id, ctx["cfg"], month)
        h = evidence_hash(ev)
        same = ctx["cfg_sk"] and conn.execute("""
            select 1 from core.fct_game_digest
            where app_id = %s and period_from = %s and llm_config_sk = %s and evidence_hash = %s
        """, (app_id, month, ctx["cfg_sk"], h)).fetchone()
        if same:
            counts["same"] += 1
            continue
        text = as_text(game, ev)
        if ctx["dry_run"]:
            est = None if ctx["price"] is None else client.price_of(
                len(ctx["prompt"]) / client.PROMPT_CHARS_PER_TOKEN + len(text) / client.TEXT_CHARS_PER_TOKEN, 0, OUTPUT_TOKENS, ctx["price"])
            ctx["estimate"] = None if est is None or ctx["estimate"] is None else ctx["estimate"] + est
            print(f"  {month:%Y-%m}: к генерации")
            continue
        problems, headline, summary, attempts, spend = generate(ctx["prompt"], text, ev, ctx["vocab"], ctx["price"])
        conn.execute("""
            insert into core.fct_game_digest (app_id, period_from, period_to, llm_config_sk, labeling_config_sk, evidence,
                evidence_hash, headline, summary, checks, checks_passed, attempts, run_id,
                input_tokens, cached_tokens, output_tokens, reasoning_tokens, cost_usd)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (app_id, month, next_month(month), ctx["cfg_sk"], ev["labeling_config_sk"], Jsonb(ev), h, headline, summary,
              Jsonb(problems), not problems, attempts, ctx["run_id"],
              spend["input"], spend["cached"], spend["output"], spend["reasoning"], spend["cost"]))
        conn.commit()
        client.add_spend(ctx["spend"], spend)
        counts["new"] += 1
        counts["flagged"] += bool(problems)
        print(f"  {month:%Y-%m}: {headline}{' | замечания: ' + str(problems) if problems else ''}")


def main():
    parser = argparse.ArgumentParser(description="Сводка месяца по игре")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--app-id", type=int)
    source.add_argument("--all-enabled", action="store_true", help="все игры, включённые в core.llm_game")
    parser.add_argument("--months", type=int, default=3, help="сколько последних завершённых месяцев")
    parser.add_argument("--dry-run", action="store_true", help="посчитать месяцы к генерации и цену - без модели и записи")
    args = parser.parse_args()

    _, model = client.settings()
    if not args.dry_run:
        client.api_key()
    prompt = PROMPT.read_text(encoding="utf-8").strip()
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    ctx = {"prompt": prompt, "price": client.prices(), "months": args.months, "dry_run": args.dry_run,
           "run_id": now.strftime("%Y%m%d-%H%M%S") + (f"-d{args.app_id}" if args.app_id else "-dall"),
           "spend": client.new_spend(), "estimate": 0.0}
    counts = {"new": 0, "same": 0, "flagged": 0}

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        cfg = conn.execute("select llm_config_sk, codebook_version from marts.llm_config_active").fetchone()
        if cfg is None:
            raise SystemExit("нет активной конфигурации разметки в marts.llm_config_active")
        if args.dry_run:
            ctx["cfg_sk"] = codebook.find_config(conn, model, prompt, PARAMS)
        else:
            ctx["cfg_sk"] = codebook.ensure_config(conn, model, prompt, PARAMS, cfg["codebook_version"], PROMPT_NAME)
            conn.commit()
        ctx["cfg"] = cfg
        ctx["vocab"] = sorted({x for r in conn.execute(
            "select aspect_id, aspect_name, category_id, category_name from core.dim_aspect where codebook_version = %s",
            (cfg["codebook_version"],)) for x in r.values()} - {"other", "Other", "overall", "Overall"}, key=len, reverse=True)
        games = [args.app_id] if args.app_id else [r["app_id"] for r in conn.execute(
            "select app_id from core.llm_game where enabled order by app_id").fetchall()]
        for app_id in games:
            process_game(conn, app_id, ctx, counts)

    print(f"новых {counts['new']} (не прошли проверки {counts['flagged']}), без изменений {counts['same']}")
    if args.dry_run:
        print(f"оценка: {client.money(ctx['estimate'])}")
        return
    spend = ctx["spend"]
    print(f"run_id {ctx['run_id']} | {time.monotonic() - started:.0f} с | {client.money(spend['cost'])} | "
          f"токены вход {spend['input']} (кэш {spend['cached']}), выход {spend['output']}")


if __name__ == "__main__":
    main()
