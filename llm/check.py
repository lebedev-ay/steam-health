"""Пачка для модели и проверка её ответа. Без сети и базы - это и тестируется."""

from llm.client import load_json
from llm.codebook import MAX_ASPECTS

SIGNS = ("+", "-", "±")
MAX_NOTE_WORDS = 3


def batch_text(texts):
    # модели уходят короткие номера 1..N, а не recommendation_id: длинные id модель путает, обратно сопоставляется по позиции
    return "\n".join(f'<review n="{n}">{text}</review>' for n, text in enumerate(texts, start=1))


def parse(content, size, allowed_ids):
    """Вернуть ({номер: [аспекты]}, ошибки). Номер без записи в результате - отзыв не прошёл проверку.

    Аспект - {"id", "sentiment", "note"}; note только у other. Кривой аспект бракует весь отзыв: частичная разметка исказила бы доли.
    Повтор аспекта отбрасывается, больше MAX_ASPECTS - остаются первые, они по важности.
    """
    items = load_json(content)
    if items is None:
        return {}, ["ответ не JSON"]
    if not isinstance(items, list):
        return {}, ["ответ не массив"]

    results, errors, rejected = {}, [], set()
    expected = range(1, size + 1)

    for item in items:
        n = item.get("n") if isinstance(item, dict) else None
        if n not in expected or n in results or n in rejected or isinstance(n, bool):
            errors.append(f"лишний или повторный номер: {n}")
            continue
        aspects = item.get("aspects")
        if not isinstance(aspects, list):
            errors.append(f"n={n}: нет списка аспектов")
            rejected.add(n)
            continue

        clean, seen, bad = [], set(), []
        for a in aspects:
            aspect_id = a.get("id") if isinstance(a, dict) else None
            sign = a.get("sentiment") if isinstance(a, dict) else None
            note = None
            if sign not in SIGNS:
                bad.append(a)
                continue
            if aspect_id == "other":
                note = str(a.get("note") or "").strip().lower()
                if not note or len(note.split()) > MAX_NOTE_WORDS:
                    bad.append(a)
                    continue
            elif aspect_id not in allowed_ids:
                bad.append(a)
                continue
            if (aspect_id, note) in seen:
                continue
            seen.add((aspect_id, note))
            clean.append({"id": aspect_id, "sentiment": sign, "note": note})

        if bad:
            errors.append(f"n={n}: кривые аспекты {bad}")
            rejected.add(n)
            continue
        results[n] = clean[:MAX_ASPECTS]

    errors += [f"пропущен номер: {n}" for n in expected if n not in results and n not in rejected]
    return results, errors
