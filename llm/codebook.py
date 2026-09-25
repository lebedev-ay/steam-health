"""Справочник аспектов и итоговый системный промпт: из файлов в core.dim_aspect и core.dim_llm_config."""

import hashlib
import json
from pathlib import Path
from string import Template

HERE = Path(__file__).parent
CODEBOOK = HERE / "codebook" / "codebook_v5.json"
PROMPT_NAME = "closed-v2"

MAX_ASPECTS = 5

# служебный аспект: тема вне справочника, по его меткам видно, чего в справочнике не хватает
OTHER = {
    "aspect_id": "other",
    "aspect_name": "Other",
    "aspect_definition": "Topic outside the codebook, named by a short label in note.",
    "category_id": "other",
    "category_name": "Other",
    "category_definition": "Topics outside the codebook.",
}


def load(path=CODEBOOK):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def aspect_rows(codebook):
    rows = [
        {
            "aspect_id": s["id"],
            "aspect_name": s["name"],
            "aspect_definition": s["definition"],
            "category_id": c["id"],
            "category_name": c["name"],
            "category_definition": c["definition"],
        }
        for c in codebook["categories"]
        for s in c["subaspects"]
    ]
    return rows + [OTHER]


def build_prompt(codebook, name=PROMPT_NAME):
    lines = []
    for c in codebook["categories"]:
        lines.append(f"[{c['name']}]")
        lines.extend(f"{s['id']}: {s['definition']}" for s in c["subaspects"])

    template = (HERE / "prompts" / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")
    return Template(template).substitute(aspects="\n".join(lines), max_aspects=MAX_ASPECTS)


def prompt_hash(prompt):
    return hashlib.sha256(prompt.encode()).hexdigest()


def sync_aspects(conn, codebook):
    """Завести строки справочника; вернуть {aspect_id: aspect_sk}. Правка уже заведённой версии - ошибка, а не тихое обновление."""
    version = codebook["version"]
    rows = aspect_rows(codebook)
    cols = list(rows[0])

    with conn.cursor() as cur:
        cur.executemany(
            f"""
            insert into core.dim_aspect (codebook_version, {", ".join(cols)})
            values (%s, {", ".join(["%s"] * len(cols))})
            on conflict (codebook_version, aspect_id) do nothing
            """,
            [(version, *(r[c] for c in cols)) for r in rows],
        )

    stored = conn.execute(
        f"select aspect_sk, {', '.join(cols)} from core.dim_aspect where codebook_version = %s",
        (version,),
    ).fetchall()
    by_id = {r["aspect_id"]: r for r in stored}

    changed = [r["aspect_id"] for r in rows
               if any(by_id[r["aspect_id"]][c] != r[c] for c in cols)]
    extra = set(by_id) - {r["aspect_id"] for r in rows}
    if changed or extra:
        raise SystemExit(f"справочник {version} в базе расходится с файлом: {changed or sorted(extra)}. "
                         "Замороженная версия не правится - нужна новая")

    return {aspect_id: r["aspect_sk"] for aspect_id, r in by_id.items()}


def find_config(conn, model, prompt):
    row = conn.execute(
        "select llm_config_sk from core.dim_llm_config where prompt_hash = %s and model = %s",
        (prompt_hash(prompt), model),
    ).fetchone()
    return row["llm_config_sk"] if row else None


def ensure_config(conn, model, prompt, codebook_version, name=PROMPT_NAME):
    conn.execute(
        """
        insert into core.dim_llm_config (model, prompt_name, codebook_version, system_prompt, prompt_hash)
        values (%s, %s, %s, %s, %s)
        on conflict (prompt_hash, model) do nothing
        """,
        (model, name, codebook_version, prompt, prompt_hash(prompt)),
    )
    return find_config(conn, model, prompt)
