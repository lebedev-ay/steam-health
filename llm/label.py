"""Разметка отзывов игры аспектами со знаком.

    python -m llm.label --app-id 892970 [--since 2026-01-01] [--until 2026-02-01] [--dry-run]
    python -m llm.label --ids-file llm/gold/gold_ids.txt [--dry-run]
    python -m llm.label --app-id 892970 --adaptive [--spike-factor 2 --spike-min-abs 60 --spike-limit 200] [--dry-run]

--ids-file размечает только отзывы из списка recommendation_id (по одному в строке), без порога длины и дневного лимита.
--adaptive в дни всплесков (содержательных отзывов не меньше spike-factor x медиана за 28 предыдущих дней и не меньше spike-min-abs)
поднимает дневной лимит до spike-limit; порядок внутри дня прежний, поэтому доразмечаются только следующие по порядку отзывы.

Уже размеченное этой конфигурацией (модель + итоговый промпт + параметры генерации) пропускается.
Отзывы короче порога только считаются: в базу не пишутся и в модель не уходят. --dry-run ничего не пишет в базу и не зовёт модель.
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
from llm.select import day_limits, plan, plan_listed
from llm.texts import candidates, content_by_day, snapshot

# DSN общий с collector/, а он не пакет - подключается так же, как в tools/
sys.path.insert(0, str(Path(__file__).parent.parent / "collector"))

from db import DSN

def money(value):
    return "цена неизвестна" if value is None else f"${value:.4f}"


def label_batch(prompt, texts, allowed_ids):
    """Вернуть ({позиция в пачке: аспекты}, usage). Сетевой сбой и обрезанный ответ - вся пачка не прошла."""
    try:
        content, finish, usage = client.complete(prompt, batch_text(texts))
    except requests.RequestException as e:
        print(f"  сетевая ошибка: {e}")
        return {}, None
    if finish != "stop":
        print(f"  ответ обрезан ({finish})")
        return {}, usage
    results, errors = parse(content, len(texts), allowed_ids)
    if errors:
        print(f"  {errors}")
    return results, usage


def save(conn, config_sk, run_id, items, aspect_sks):
    """items - (review_text_sk, статус, day_rank, аспекты). Перезаписывается только failed."""
    for text_sk, status, rank, aspects in items:
        row = conn.execute(
            """
            insert into core.fct_review_labeling (review_text_sk, llm_config_sk, status, run_id, day_rank)
            values (%s, %s, %s, %s, %s)
            on conflict (review_text_sk, llm_config_sk) do update
                set status = excluded.status, run_id = excluded.run_id,
                    day_rank = excluded.day_rank, labeled_at = now()
                where core.fct_review_labeling.status = 'failed'
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
    """todo - (review_text_sk, текст, day_rank). Пачки по batch_size из параметров, упавшие - поштучно.

    Вернуть (счётчики, расход): токены вход/кэш/выход и цена; цена None, если хоть одну пачку оценить не удалось.
    """
    allowed = set(aspect_sks) - {"other"}
    counts = {"labeled": 0, "no_opinion": 0, "failed": 0}
    spend = {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost": 0.0}
    price, failed = client.prices(), []

    def process(batch):
        results, usage = label_batch(prompt, [t for _, t, _ in batch], allowed)
        if usage is not None:   # сетевой сбой - вызова не было, платить не за что
            for key, n in zip(("input", "cached", "output"), client.tokens(usage)):
                spend[key] += n
            spend["reasoning"] += client.reasoning_tokens(usage)
            batch_cost = client.cost(usage, price)
            spend["cost"] = None if batch_cost is None or spend["cost"] is None else spend["cost"] + batch_cost
        done = [(sk, "labeled" if results[n] else "no_opinion", rank, results[n])
                for n, (sk, _, rank) in enumerate(batch, start=1) if n in results]
        save(conn, config_sk, run_id, done, aspect_sks)
        for _, status, _, _ in done:
            counts[status] += 1
        return [item for n, item in enumerate(batch, start=1) if n not in results]

    size = client.GENERATION["batch_size"]
    for start in range(0, len(todo), size):
        failed += process(todo[start:start + size])
        print(f"  {min(start + size, len(todo))} из {len(todo)}")

    if failed:
        print(f"повтор поштучно: {len(failed)}")
        still = [item for one in failed for item in process([one])]
        save(conn, config_sk, run_id, [(sk, "failed", rank, []) for sk, _, rank in still], aspect_sks)
        counts["failed"] = len(still)

    return counts, spend


def parse_args():
    parser = argparse.ArgumentParser(description="LLM-разметка отзывов игры")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--app-id", type=int)
    source.add_argument("--ids-file", type=Path, help="файл с recommendation_id по одному в строке")
    parser.add_argument("--since", type=date.fromisoformat, help="created_at отзыва от, UTC, включительно")
    parser.add_argument("--until", type=date.fromisoformat, help="created_at отзыва до, UTC, исключительно")
    parser.add_argument("--day-limit", type=int, default=30, help="отзывов на игру в день")
    parser.add_argument("--min-length", type=int, default=20, help="короче - только в счёт, без модели и записи")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, без модели и записи в базу")
    parser.add_argument("--adaptive", action="store_true",
                        help="в дни всплесков лимит --spike-limit вместо --day-limit")
    parser.add_argument("--spike-factor", type=float, default=2,
                        help="всплеск: содержательных не меньше медианы за 28 дней, умноженной на это число")
    parser.add_argument("--spike-min-abs", type=int, default=60, help="всплеск: и не меньше этого числа содержательных")
    parser.add_argument("--spike-limit", type=int, default=200, help="лимит разметки в день всплеска")
    args = parser.parse_args()
    if args.ids_file and (args.since or args.until):
        parser.error("--ids-file не сочетается с --since и --until")
    if args.ids_file and args.adaptive:
        parser.error("--adaptive работает с --app-id: у списка id дневного лимита нет")
    return args


def read_ids(path):
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [int(line) for line in lines if line and not line.startswith("#")]


def main():
    args = parse_args()
    _, model = client.settings()
    if not args.dry_run:
        client.api_key()   # без ключа выход до любой записи в базу
    book = codebook.load()
    prompt = codebook.build_prompt(book)

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        if args.dry_run:
            config_sk, aspect_sks = codebook.find_config(conn, model, prompt, client.GENERATION), {}
        else:
            aspect_sks = codebook.sync_aspects(conn, book)
            config_sk = codebook.ensure_config(conn, model, prompt, client.GENERATION, book["version"])
            conn.commit()

        print(f"справочник {book['version']} | промпт {codebook.PROMPT_NAME} ({codebook.prompt_hash(prompt)[:8]}) | {model}")
        if args.ids_file:
            ids = read_ids(args.ids_file)
            rows = candidates(conn, config_sk, ids=ids)
            p = plan_listed(rows)
            missing = set(ids) - {r["recommendation_id"] for r in rows}
            print(f"отзывов в списке: {len(ids)} | нет в базе: {len(missing)} | уже размечено: {p['done']} | "
                  f"в работу: {len(p['to_label'])} (из них повтор failed: {p['retry']})")
            if missing:
                print(f"  нет в core.fct_review или без текста: {sorted(missing)}")
        else:
            rows = candidates(conn, config_sk, args.app_id, args.since, args.until)
            limits = None
            if args.adaptive:
                days = day_limits(content_by_day(conn, args.app_id, args.min_length), args.day_limit,
                                  args.spike_factor, args.spike_min_abs, args.spike_limit)
                period = {r["day"] for r in rows}
                spikes = sorted(d for d, v in days.items() if v["spike"] and d in period)
                limits = {d: v["limit"] for d, v in days.items()}
                base = plan(rows, args.min_length, args.day_limit)
            p = plan(rows, args.min_length, args.day_limit, limits)
            limit_note = f"{args.day_limit}/день, во всплеск {args.spike_limit}" if args.adaptive else f"{args.day_limit}/день"
            print(f"отзывов в периоде: {len(rows)} | короче {args.min_length}: {p['too_short']} | "
                  f"сверх лимита {limit_note}: {p['over_limit']} | уже размечено: {p['done']} | "
                  f"в работу: {len(p['to_label'])} (из них повтор failed: {p['retry']})")
            if args.adaptive:
                print(f"всплесков: {len(spikes)} (содержательных >= {args.spike_factor:g} x медиана за 28 дней "
                      f"и >= {args.spike_min_abs}) | к обычному лимиту добавится: {len(p['to_label']) - len(base['to_label'])}")
                for d in spikes[:20]:
                    v = days[d]
                    print(f"  {d:%d.%m.%Y}  содержательных {v['content']:>5}  медиана {v['median']:>6g}  лимит {v['limit']}")
                if len(spikes) > 20:
                    print(f"  ... и ещё {len(spikes) - 20}")
        chars = sum(r["length"] for r in p["to_label"])

        if args.dry_run:
            est = client.estimate(prompt, chars, len(p["to_label"]), client.prices())
            note = "" if est is not None else " (не заданы LLM_PRICE_INPUT и LLM_PRICE_OUTPUT)"
            print(f"оценка: {money(est)}{note}, текста {chars} символов")
            return

        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{args.app_id or 'ids'}"

        order = sorted(p["to_label"], key=lambda r: (r["day"], r["day_rank"] or 0, r["recommendation_id"]))
        texts = snapshot(conn, [r["recommendation_id"] for r in order])
        conn.commit()
        todo = [(*texts[r["recommendation_id"]], r["day_rank"]) for r in order]

        started = time.monotonic()
        counts, spend = run(conn, todo, prompt, config_sk, run_id, aspect_sks)
        print(f"run_id {run_id} | {time.monotonic() - started:.0f} с | {money(spend['cost'])} | "
              f"токены вход {spend['input']} (кэш {spend['cached']}), выход {spend['output']} "
              f"(размышления {spend['reasoning']}) | "
              f"labeled {counts['labeled']} | no_opinion {counts['no_opinion']} | failed {counts['failed']}")


if __name__ == "__main__":
    main()
