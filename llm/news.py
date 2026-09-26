"""Разметка новостей игры: масштаб события для игры, вид, анонс это или уже случилось, короткое русское название.

    python -m llm.news --app-id 892970 [--since 2025-01-01] [--dry-run]
    python -m llm.news --all [--dry-run]                   - все игры: новостей в сотни раз меньше, чем отзывов
    python -m llm.news --export-sample 60 > llm/gold/news_gold.json   - выборка для эталона: поля tier, kind, future заполнить руками
    python -m llm.news --eval llm/gold/news_gold.json      - сравнить разметку активной конфигурации с эталоном

Размечаются собственные новости игры (feed_type = 1): пресса - чужой взгляд на игру, а не событие игры. Модель видит заголовок и
начало текста без разметки Steam. Уже размеченное этой конфигурацией с тем же текстом пропускается, упавшая пачка - повтор поштучно.
"""

import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import requests
from psycopg.rows import dict_row

from llm import client, codebook
from llm.verdict_check import foreign_letters

from db import DSN

PROMPT_NAME = "news-v1"
PROMPT = Path(__file__).parent / "prompts" / "news_v1.txt"
BATCH = 15
PARAMS = {**{k: client.GENERATION[k] for k in ("temperature", "max_tokens", "reasoning")}, "batch_size": BATCH}
BODY_CHARS = 800
TITLE_RU_CHARS = 40
OUTPUT_TOKENS_PER_NEWS = 45     # оценка выхода для --dry-run: объект JSON на новость
PLATFORM_APP_ID = 753           # фид платформы Steam - не игра, у него своя таблица событий

TIERS = ("milestone", "major", "regular", "background")
KINDS = ("release", "expansion", "major_update", "season", "content_update", "balance", "hotfix", "event", "roadmap",
         "announcement", "sale", "community", "other")


# =============================================================================
# Текст для модели и проверка ответа - без базы, это и тестируется
# =============================================================================

BBCODE = re.compile(r"\[/?[a-z0-9*]+(?:=[^\]]*)?\]", re.I)
IMAGE = re.compile(r"\[img\].*?\[/img\]|\{STEAM_CLAN_IMAGE\}\S*|\{STEAM_[A-Z_]+\}\S*", re.I | re.S)
HTML = re.compile(r"<[^>]+>")
URL = re.compile(r"https?://\S+")


def clean(text, limit=BODY_CHARS):
    """Текст новости без разметки Steam, картинок и ссылок, до limit символов по границе слова."""
    text = IMAGE.sub(" ", text or "")
    text = URL.sub(" ", HTML.sub(" ", BBCODE.sub(" ", text)))
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut[:cut.rfind(" ")] if " " in cut else cut) + "…"


def text_hash(title, body):
    return hashlib.md5(f"{title or ''}\n{body or ''}".encode()).hexdigest()


def batch_text(items):
    # модели уходят короткие номера 1..N, а не gid: длинные id модель путает, обратно сопоставляется по позиции
    return "\n".join(
        f'<news n="{n}" date="{i["date"]}" game="{i["game"]}">{i["title"]}\n{clean(i["body"])}</news>'
        for n, i in enumerate(items, start=1))


def parse(content, size):
    """Вернуть ({номер: разметка}, ошибки). Кривой объект бракует только свою новость: соседние в пачке от него не зависят."""
    items = client.load_json(content)
    if items is None:
        return {}, ["ответ не JSON"]
    if not isinstance(items, list):
        return {}, ["ответ не массив"]

    results, errors = {}, []
    for item in items:
        n = item.get("n") if isinstance(item, dict) else None
        if isinstance(n, bool) or n not in range(1, size + 1) or n in results:
            errors.append(f"лишний или повторный номер: {n}")
            continue
        tier, kind, future = item.get("tier"), item.get("kind"), item.get("future")
        title = str(item.get("title_ru") or "").strip().rstrip(".").strip("«»\"' ")
        problems = []
        if tier not in TIERS:
            problems.append(f"tier {tier!r}")
        if kind not in KINDS:
            problems.append(f"kind {kind!r}")
        if not isinstance(future, bool):
            problems.append(f"future {future!r}")
        if not 2 <= len(title) <= TITLE_RU_CHARS:
            problems.append(f"title_ru длиной {len(title)}")
        if not re.search(r"[а-яё]", title, re.I):
            problems.append("title_ru без русских слов")
        if foreign_letters(title):
            problems.append(f"title_ru с буквами не кириллицы и не латиницы «{''.join(foreign_letters(title))}»")
        if problems:
            errors.append(f"n={n}: {', '.join(problems)}")
            continue
        results[n] = {"tier": tier, "kind": kind, "is_future": future, "title_ru": title}
    errors += [f"пропущен номер: {n}" for n in range(1, size + 1) if n not in results and not any(e.startswith(f"n={n}:") for e in errors)]
    return results, errors


# =============================================================================
# Кандидаты, разметка, запись
# =============================================================================

def candidates(conn, config_sk, app_ids=None, since=None, gids=None):
    """Собственные новости игр из сырья: последняя сохранённая версия каждой gid и статус её разметки этой конфигурацией."""
    conds, params = ["(item ->> 'feed_type')::int = 1", "n.app_id <> %(platform)s",
                     "coalesce(item ->> 'feedname', '') <> 'SteamDB'"], {"platform": PLATFORM_APP_ID, "cfg": config_sk}
    if app_ids is not None:
        conds.append("n.app_id = any(%(apps)s)")
        params["apps"] = list(app_ids)
    if since is not None:
        conds.append("to_timestamp((item ->> 'date')::bigint) >= %(since)s")
        params["since"] = since
    if gids is not None:
        conds.append("item ->> 'gid' = any(%(gids)s)")
        params["gids"] = list(gids)
    rows = conn.execute(f"""
        with news as (
            select distinct on (item ->> 'gid')
                   item ->> 'gid' as gid, n.app_id, item ->> 'title' as title, item ->> 'contents' as body,
                   to_timestamp((item ->> 'date')::bigint)::date as date
            from raw.news n, jsonb_array_elements(n.payload -> 'appnews' -> 'newsitems') as item
            where {" and ".join(conds)}
            order by item ->> 'gid', n.fetched_at desc
        )
        select n.*, coalesce(g.game_name, n.app_id::text) as game,
               (select l.status from core.fct_news_label l
                where l.gid = n.gid and l.llm_config_sk = %(cfg)s and l.text_hash = md5(coalesce(n.title, '') || chr(10) || coalesce(n.body, ''))
                order by l.labeled_at desc limit 1) as status
        from news n
        left join core.dim_game g on g.app_id = n.app_id and g.is_current
        order by n.date desc, n.gid
    """, params).fetchall()
    return rows


def save(conn, config_sk, run_id, pairs):
    """pairs - (новость, разметка или None). Перезаписывается только failed: размеченное этой конфигурацией не трогаем."""
    for item, r in pairs:
        conn.execute("""
            insert into core.fct_news_label (gid, text_hash, llm_config_sk, status, tier, kind, is_future, title_ru, run_id)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (gid, text_hash, llm_config_sk) do update
                set status = excluded.status, tier = excluded.tier, kind = excluded.kind, is_future = excluded.is_future,
                    title_ru = excluded.title_ru, run_id = excluded.run_id, labeled_at = now()
                where core.fct_news_label.status = 'failed'
        """, (item["gid"], text_hash(item["title"], item["body"]), config_sk, "labeled" if r else "failed",
              *((r["tier"], r["kind"], r["is_future"], r["title_ru"]) if r else (None, None, None, None)), run_id))
    conn.commit()


def label_batch(prompt, items):
    """Вернуть ({номер: разметка}, usage). Сетевой сбой и обрезанный ответ - пачка не прошла целиком."""
    try:
        content, finish, usage = client.complete(prompt, batch_text(items))
    except requests.RequestException as e:
        print(f"  сетевая ошибка: {e}")
        return {}, None
    if finish != "stop":
        print(f"  ответ обрезан ({finish})")
        return {}, usage
    results, errors = parse(content, len(items))
    if errors:
        print(f"  {errors}")
    return results, usage


def run(conn, todo, prompt, config_sk, run_id):
    """Пачками по BATCH, не прошедшие - поштучно. Вернуть (размечено, упало, расход)."""
    price, spend, failed = client.prices(), client.new_spend(), []

    def process(batch):
        results, usage = label_batch(prompt, batch)
        if usage is not None:
            client.add_spend(spend, client.spend_of(usage, price))
        save(conn, config_sk, run_id, [(item, results[n]) for n, item in enumerate(batch, start=1) if n in results])
        return [item for n, item in enumerate(batch, start=1) if n not in results]

    for start in range(0, len(todo), BATCH):
        failed += process(todo[start:start + BATCH])
        print(f"  {min(start + BATCH, len(todo))} из {len(todo)}")
    still = []
    if failed:
        print(f"повтор поштучно: {len(failed)}")
        still = [i for one in failed for i in process([one])]
        save(conn, config_sk, run_id, [(item, None) for item in still])
    return len(todo) - len(still), len(still), spend


# =============================================================================
# Эталон
# =============================================================================

def export_sample(conn, n):
    """Выборка для эталона: половина - самые весомые и сезонные по нынешнему классификатору, половина - случайные.

    Без перекоса в весомые в выборку попали бы почти одни хотфиксы и блоги, и проверять уровень «веха» было бы не на чем.
    """
    rows = candidates(conn, None)
    weight = {r["gid"]: r for r in conn.execute("""
        select distinct on (gid) gid, event_type, weight from core.fct_patch order by gid, weight desc nulls last
    """).fetchall()}
    heavy = sorted((r for r in rows if r["gid"] in weight),
                   key=lambda r: (weight[r["gid"]]["event_type"] not in ("season_start", "expansion"), -(weight[r["gid"]]["weight"] or 0)))
    picked = heavy[:n // 2]
    taken = {r["gid"] for r in picked}
    rest = sorted((r for r in rows if r["gid"] not in taken), key=lambda r: hashlib.md5(r["gid"].encode()).hexdigest())
    picked += rest[:n - len(picked)]
    return [{"gid": r["gid"], "game": r["game"], "date": r["date"].isoformat(), "title": r["title"],
             "excerpt": clean(r["body"], 300), "tier": "", "kind": "", "future": None} for r in picked]


def evaluate(conn, gold_path, config_sk):
    gold = {g["gid"]: g for g in json.loads(Path(gold_path).read_text(encoding="utf-8")) if g.get("tier")}
    labels = {r["gid"]: r for r in conn.execute("""
        select distinct on (gid) gid, tier, kind, is_future, title_ru from core.fct_news_label
        where llm_config_sk = %s and status = 'labeled' and gid = any(%s) order by gid, labeled_at desc
    """, (config_sk, list(gold))).fetchall()}
    both = [g for g in gold if g in labels]
    print(f"в эталоне {len(gold)}, размечено моделью {len(both)}")
    if not both:
        return
    for field, key in (("tier", "tier"), ("kind", "kind"), ("future", "is_future")):
        same = sum(gold[g][field] == labels[g][key] for g in both if gold[g].get(field) not in ("", None))
        total = sum(gold[g].get(field) not in ("", None) for g in both)
        print(f"{field:<7} совпало {same} из {total}" + (f" ({same / total:.0%})" if total else ""))
    print("\nуровень: строки - эталон, столбцы - модель")
    print(" " * 12 + "".join(f"{t:>12}" for t in TIERS))
    for t in TIERS:
        print(f"{t:<12}" + "".join(f"{sum(gold[g]['tier'] == t and labels[g]['tier'] == m for g in both):>12}" for m in TIERS))
    # самое дорогое расхождение - пропущенная или выдуманная веха: она решает, что видно на графике всегда
    wrong = [g for g in both if (gold[g]["tier"] == "milestone") != (labels[g]["tier"] == "milestone")]
    if wrong:
        print("\nрасхождения по вехам:")
        for g in wrong:
            print(f"  {gold[g]['date']} {gold[g]['game']}: «{gold[g]['title'][:70]}» - эталон {gold[g]['tier']}, модель {labels[g]['tier']}")


# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="LLM-разметка новостей игр")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--app-id", type=int)
    source.add_argument("--all", action="store_true", help="все игры с новостями в сырье")
    source.add_argument("--export-sample", type=int, metavar="N", help="выборка для эталона в stdout")
    source.add_argument("--eval", type=Path, metavar="GOLD", help="сравнить с эталоном")
    source.add_argument("--ids-file", type=Path, help="разметить новости из эталона (JSON с полем gid)")
    parser.add_argument("--since", type=date.fromisoformat, help="новости не старше этой даты")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать и оценить цену")
    args = parser.parse_args()

    prompt = PROMPT.read_text(encoding="utf-8").strip()
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        if args.export_sample:
            print(json.dumps(export_sample(conn, args.export_sample), ensure_ascii=False, indent=1))
            return
        _, model = client.settings()
        if args.eval:
            config_sk = codebook.find_config(conn, model, prompt, PARAMS)
            if config_sk is None:
                raise SystemExit("эта конфигурация новости ещё не размечала - сначала --ids-file с тем же эталоном")
            evaluate(conn, args.eval, config_sk)
            return
        if not args.dry_run:
            client.api_key()
            config_sk = codebook.ensure_config(conn, model, prompt, PARAMS, "news", PROMPT_NAME)
            conn.commit()
        else:
            config_sk = codebook.find_config(conn, model, prompt, PARAMS)

        gids = [g["gid"] for g in json.loads(args.ids_file.read_text(encoding="utf-8"))] if args.ids_file else None
        rows = candidates(conn, config_sk, [args.app_id] if args.app_id else None, args.since, gids)
        todo = [r for r in rows if r["status"] != "labeled"]
        print(f"промпт {PROMPT_NAME} ({codebook.prompt_hash(prompt)[:8]}) | {model} | новостей {len(rows)} | "
              f"уже размечено {len(rows) - len(todo)} | в работу {len(todo)}")
        if args.dry_run:
            chars = sum(len(r["title"] or "") + len(clean(r["body"])) for r in todo)
            est = client.estimate(prompt, chars, len(todo), client.prices(), batch_size=BATCH,
                                  output_per_item=OUTPUT_TOKENS_PER_NEWS, tag_chars=60)
            print(f"оценка: {client.money(est)}, текста {chars} символов")
            return

        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-n{args.app_id or 'all'}"
        started = time.monotonic()
        done, failed, spend = run(conn, todo, prompt, config_sk, run_id)
        print(f"run_id {run_id} | {time.monotonic() - started:.0f} с | {client.money(spend['cost'])} | размечено {done}, "
              f"упало {failed} | токены вход {spend['input']} (кэш {spend['cached']}), выход {spend['output']}")


if __name__ == "__main__":
    main()
