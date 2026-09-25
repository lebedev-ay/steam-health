"""Разметка отзывов игры аспектами со знаком.

    python -m llm.label --app-id 892970 [--since 2026-01-01] [--until 2026-02-01] [--dry-run]

Уже размеченное этой конфигурацией (модель + итоговый промпт) пропускается. --dry-run ничего не пишет в базу и не зовёт модель.
"""

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import requests
from psycopg.rows import dict_row

from llm import client, codebook
from llm.check import batch_text, parse
from llm.select import plan
from llm.texts import candidates, snapshot

# DSN общий с collector/, а он не пакет - подключается так же, как в tools/
sys.path.insert(0, str(Path(__file__).parent.parent / "collector"))

from db import DSN

BATCH_SIZE = 10

# оценка цены по полному прогону разведки на qwen3.8-flash: 2957 отзывов, 1.66 млн символов, $0.19 (exploration.md)
COST_PER_MCHAR = 0.115
COST_PER_REVIEW = 0.000064


def label_batch(prompt, texts, allowed_ids):
    """Вернуть ({позиция в пачке: аспекты}, цена). Сетевой сбой и обрезанный ответ - вся пачка не прошла."""
    try:
        content, finish, cost = client.complete(prompt, batch_text(texts))
    except requests.RequestException as e:
        print(f"  сетевая ошибка: {e}")
        return {}, 0
    if finish != "stop":
        print(f"  ответ обрезан ({finish})")
        return {}, cost or 0
    results, errors = parse(content, len(texts), allowed_ids)
    if errors:
        print(f"  {errors}")
    return results, cost or 0


def save(conn, config_sk, run_id, items, aspect_sks):
    """items - (review_text_sk, статус, day_rank, аспекты). Перезаписываются только failed и too_short."""
    for text_sk, status, rank, aspects in items:
        row = conn.execute(
            """
            insert into core.fct_review_labeling (review_text_sk, llm_config_sk, status, run_id, day_rank)
            values (%s, %s, %s, %s, %s)
            on conflict (review_text_sk, llm_config_sk) do update
                set status = excluded.status, run_id = excluded.run_id,
                    day_rank = excluded.day_rank, labeled_at = now()
                where core.fct_review_labeling.status in ('failed', 'too_short')
            returning labeling_sk
            """,
            (text_sk, config_sk, status, run_id, rank),
        ).fetchone()
        if row is None:
            continue
        for importance, a in enumerate(aspects, start=1):
            conn.execute(
                """
                insert into core.fct_review_aspect (labeling_sk, importance, aspect_sk, sentiment, note)
                values (%s, %s, %s, %s, %s)
                """,
                (row["labeling_sk"], importance, aspect_sks[a["id"]], a["sentiment"], a["note"]),
            )
    conn.commit()


def run(conn, todo, prompt, config_sk, run_id, aspect_sks):
    """todo - (review_text_sk, текст, day_rank). Пачки по BATCH_SIZE, упавшие - поштучно. Вернуть (счётчики, цена)."""
    allowed = set(aspect_sks) - {"other"}
    counts = {"labeled": 0, "no_opinion": 0, "failed": 0}
    total_cost, failed = 0, []

    def process(batch):
        nonlocal total_cost
        results, cost = label_batch(prompt, [t for _, t, _ in batch], allowed)
        total_cost += cost
        done = [(sk, "labeled" if results[n] else "no_opinion", rank, results[n])
                for n, (sk, _, rank) in enumerate(batch, start=1) if n in results]
        save(conn, config_sk, run_id, done, aspect_sks)
        for _, status, _, _ in done:
            counts[status] += 1
        return [item for n, item in enumerate(batch, start=1) if n not in results]

    for start in range(0, len(todo), BATCH_SIZE):
        failed += process(todo[start:start + BATCH_SIZE])
        print(f"  {min(start + BATCH_SIZE, len(todo))} из {len(todo)}")

    if failed:
        print(f"повтор поштучно: {len(failed)}")
        still = [item for one in failed for item in process([one])]
        save(conn, config_sk, run_id, [(sk, "failed", rank, []) for sk, _, rank in still], aspect_sks)
        counts["failed"] = len(still)

    return counts, total_cost


def parse_args():
    parser = argparse.ArgumentParser(description="LLM-разметка отзывов игры")
    parser.add_argument("--app-id", type=int, required=True)
    parser.add_argument("--since", type=date.fromisoformat, help="created_at отзыва от, UTC, включительно")
    parser.add_argument("--until", type=date.fromisoformat, help="created_at отзыва до, UTC, исключительно")
    parser.add_argument("--day-limit", type=int, default=30, help="отзывов на игру в день")
    parser.add_argument("--min-length", type=int, default=20, help="короче - too_short без вызова модели")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, без модели и записи в базу")
    return parser.parse_args()


def main():
    args = parse_args()
    _, model = client.settings()
    book = codebook.load()
    prompt = codebook.build_prompt(book)

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        if args.dry_run:
            config_sk, aspect_sks = codebook.find_config(conn, model, prompt), {}
        else:
            aspect_sks = codebook.sync_aspects(conn, book)
            config_sk = codebook.ensure_config(conn, model, prompt, book["version"])
            conn.commit()

        rows = candidates(conn, args.app_id, args.since, args.until, config_sk)
        p = plan(rows, args.min_length, args.day_limit)
        chars = sum(r["length"] for r in p["to_label"])

        print(f"справочник {book['version']} | промпт {codebook.PROMPT_NAME} ({codebook.prompt_hash(prompt)[:8]}) | {model}")
        print(f"отзывов в периоде: {len(rows)} | короче {args.min_length}: {len(p['too_short']) + p['short_known']} "
              f"(новых {len(p['too_short'])}) | сверх лимита {args.day_limit}/день: {p['over_limit']} | "
              f"уже размечено: {p['done']} | в работу: {len(p['to_label'])} (из них повтор failed/too_short: {p['retry']})")

        if args.dry_run:
            print(f"оценка: ${chars * COST_PER_MCHAR / 1e6:.4f} по символам ({chars}), "
                  f"${len(p['to_label']) * COST_PER_REVIEW:.4f} по средней цене отзыва разведки")
            return

        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{args.app_id}"

        short = snapshot(conn, [r["recommendation_id"] for r in p["too_short"]])
        save(conn, config_sk, run_id, [(sk, "too_short", None, []) for sk, _ in short.values()], aspect_sks)

        order = sorted(p["to_label"], key=lambda r: (r["day"], r["day_rank"]))
        texts = snapshot(conn, [r["recommendation_id"] for r in order])
        conn.commit()
        todo = [(*texts[r["recommendation_id"]], r["day_rank"]) for r in order]

        started = time.monotonic()
        counts, cost = run(conn, todo, prompt, config_sk, run_id, aspect_sks)
        print(f"run_id {run_id} | {time.monotonic() - started:.0f} с | ${cost:.4f} | "
              f"labeled {counts['labeled']} | no_opinion {counts['no_opinion']} | failed {counts['failed']} | "
              f"too_short {len(short)}")


if __name__ == "__main__":
    main()
