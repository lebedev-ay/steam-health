"""Сравнение разметки модели из базы с эталоном: два разметчика и модель.

    python -m llm.eval [--config-sk N]

По умолчанию берётся конфигурация из окружения (LLM_MODEL + текущий промпт + параметры генерации).
Сначала эталон размечается той же конфигурацией: python -m llm.label --ids-file llm/eval/gold_ids.txt
Согласие - коэффициент Дайса по парам (отзыв, аспект): 2|A∩B| / (|A| + |B|).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from llm import client, codebook

# DSN общий с collector/, а он не пакет - подключается так же, как в tools/
sys.path.insert(0, str(Path(__file__).parent.parent / "collector"))

from db import DSN

GOLD = Path(__file__).parent / "eval"
RATERS = {"Антон": GOLD / "gold_anton_v4.json", "Claude": GOLD / "gold_claude.json"}
OVERALL = "overall_impression"


def load_gold(path):
    """{recommendation_id: {аспект: знак}}"""
    with open(path, encoding="utf-8") as f:
        return {int(r["id"]): {a["id"]: a["sentiment"] for a in r["aspects"]} for r in json.load(f)}


def load_model(conn, config_sk, ids):
    """Разметка текущих версий текстов этой конфигурацией; failed считается неразмеченным."""
    rows = conn.execute("""
        select v.recommendation_id, a.aspect_id, t.sentiment
        from core.review_text_version v
        join core.fct_review_labeling l
          on l.review_text_sk = v.review_text_sk and l.llm_config_sk = %s and l.status <> 'failed'
        left join core.fct_review_aspect t on t.labeling_sk = l.labeling_sk
        left join core.dim_aspect a on a.aspect_sk = t.aspect_sk
        where v.is_current and v.recommendation_id = any(%s)
        order by v.recommendation_id, t.importance
    """, (config_sk, list(ids))).fetchall()

    labels = {}
    for r in rows:
        aspects = labels.setdefault(r["recommendation_id"], {})
        if r["aspect_id"] is not None:
            aspects.setdefault(r["aspect_id"], r["sentiment"])
    return labels


def pairs(labels, ids, exclude, to_category=None):
    return {(rid, to_category.get(a, a) if to_category else a)
            for rid in ids for a in labels.get(rid, {}) if a not in exclude}


def dice(a, b):
    return 2 * len(a & b) / (len(a) + len(b)) if a or b else 1.0


def sign_agreement(x, y, ids, exclude):
    """(совпало, всего) среди аспектов, которые отметили обе разметки."""
    both = [(s, y[rid][a]) for rid in ids for a, s in x.get(rid, {}).items()
            if a not in exclude and a in y.get(rid, {})]
    return sum(s == t for s, t in both), len(both)


def report(raters, ids, to_category):
    names = list(raters)
    for exclude, title in [({OVERALL}, f"без {OVERALL}"), (set(), f"с {OVERALL}")]:
        print(f"\n--- {title} ---")
        print(f"{'пара':<18}{'подаспекты':>12}{'категории':>12}{'знак':>12}")
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                sub = dice(pairs(raters[x], ids, exclude), pairs(raters[y], ids, exclude))
                cat = dice(pairs(raters[x], ids, exclude, to_category), pairs(raters[y], ids, exclude, to_category))
                same, total = sign_agreement(raters[x], raters[y], ids, exclude)
                print(f"{x + ' - ' + y:<18}{sub:>11.0%}{cat:>12.0%}{f'{same}/{total}':>12}")

    # перекосы модели считаются без overall: по нему правила у разметчиков разные
    people = [pairs(raters[n], ids, {OVERALL}) for n in names[:2]]
    model = pairs(raters["модель"], ids, {OVERALL})
    extra = Counter(a for _, a in model - people[0] - people[1])
    missed = Counter(a for _, a in (people[0] & people[1]) - model)

    print("\nМодель ставит, ни один человек не ставит (кандидаты в натягивание):")
    for aspect, n in extra.most_common(10):
        print(f"  {n:3}  {aspect}")
    print("\nОба человека ставят, модель пропускает:")
    for aspect, n in missed.most_common(10):
        print(f"  {n:3}  {aspect}")

    # по правилу overall ставится только без конкретных причин - вместе с конкретными аспектами это нарушение
    print(f"\n{OVERALL}: всего / вместе с конкретными аспектами, из {len(ids)} отзывов")
    for name, labels in raters.items():
        with_overall = [rid for rid in ids if OVERALL in labels.get(rid, {})]
        mixed = sum(len(labels[rid]) > 1 for rid in with_overall)
        print(f"  {name:<8}{len(with_overall):>4} ({len(with_overall) / len(ids):.0%}) / {mixed}")


def main():
    parser = argparse.ArgumentParser(description="Сравнение разметки модели с эталоном")
    parser.add_argument("--config-sk", type=int, help="конфигурация из core.dim_llm_config; по умолчанию - из окружения")
    args = parser.parse_args()

    raters = {name: load_gold(path) for name, path in RATERS.items()}
    ids = sorted(set.intersection(*(set(r) for r in raters.values())))
    book = codebook.load()
    to_category = {r["aspect_id"]: r["category_id"] for r in codebook.aspect_rows(book)}

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        config_sk = args.config_sk
        if config_sk is None:
            _, model = client.settings()
            config_sk = codebook.find_config(conn, model, codebook.build_prompt(book), client.GENERATION)
            if config_sk is None:
                raise SystemExit(f"конфигурации {model} с текущим промптом и параметрами в базе нет - эталон ещё не размечался")
        config = conn.execute(
            "select model, prompt_name, codebook_version, left(prompt_hash, 8) as hash, params "
            "from core.dim_llm_config where llm_config_sk = %s", (config_sk,)).fetchone()
        if config is None:
            raise SystemExit(f"нет конфигурации {config_sk}")
        raters["модель"] = load_model(conn, config_sk, ids)

    missing = [rid for rid in ids if rid not in raters["модель"]]
    print(f"конфигурация {config_sk}: {config['model']} | {config['prompt_name']} ({config['hash']}) | "
          f"справочник {config['codebook_version']} | {json.dumps(config['params'])}")
    print(f"отзывов в сравнении: {len(ids)} | размечено моделью: {len(ids) - len(missing)}")
    if missing:
        print("  нет разметки модели для:", missing)

    report(raters, ids, to_category)


if __name__ == "__main__":
    main()
