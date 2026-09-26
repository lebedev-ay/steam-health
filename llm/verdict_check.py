"""Выводы по переломам: хэш улик, статус, отрывки для дашборда и проверки ответа модели. Без сети и базы - это и тестируется."""

import hashlib
import json
import math
import re
import unicodedata
from datetime import timedelta

from llm.client import load_json

WINDOW = 7
LATE_REVIEWS_DAYS = 3        # запас на поздние отзывы: окно «после» считается закрытым через 3 дня после конца
FIELDS = ("what_happened", "what_players_say")
EXCERPTS = 3
EXCERPT_CHARS = 150


def percent(share):
    """Доля в целых процентах с округлением половины вверх: format(0.025, ".0%") даёт 2% - банковское округление расходится с привычным."""
    return math.floor(share * 100 + 0.5)


def evidence_hash(evidence):
    """sha256 канонического JSON улик. votes_up в хэш не входит: счётчик растёт при каждом пересборе отзывов,
    и вывод пересчитывался бы без изменения содержания."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "votes_up"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    canon = json.dumps(strip(evidence), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def status(change_date, today):
    return "final" if today >= change_date + timedelta(days=WINDOW + LATE_REVIEWS_DAYS) else "preliminary"


def excerpt_text(text, limit=EXCERPT_CHARS):
    """Отрывок до limit символов с обрезкой по границе слова."""
    text = " ".join(text.replace("…", " ").split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


# дашборд русскоязычный: сначала русские опоры, затем английские; прочие языки - только если ни тех, ни других нет
EXCERPT_LANGUAGES = ("russian", "english")


def excerpts(support, reviews, languages, k=EXCERPTS):
    """До k отрывков из отзывов-опор: по языку в порядке EXCERPT_LANGUAGES, внутри языка - по votes_up.

    reviews - {номер: {votes_up, text, ...}}, languages - {номер: код языка Steam}.
    """
    pool = [n for n in set(support) if n in reviews]
    preferred = [n for n in pool if languages.get(n) in EXCERPT_LANGUAGES]
    rank = {lang: i for i, lang in enumerate(EXCERPT_LANGUAGES)}
    chosen = sorted(preferred or pool,
                    key=lambda n: (rank.get(languages.get(n), len(rank)), -reviews[n]["votes_up"], n))[:k]
    return [{"number": n, "votes_up": reviews[n]["votes_up"], "text": excerpt_text(reviews[n]["text"])} for n in chosen]


# =============================================================================
# Проверки ответа модели
# =============================================================================

REF = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
SNAKE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
FROM_TO = re.compile(r"с\s+\d+(?:[.,]\d+)?\s*%\s+до\s+\d+(?:[.,]\d+)?\s*%")
NUMBER_PAIR = re.compile(r"\d+(?:[.,]\d+)?\s*%[^%]{0,60}?\d+(?:[.,]\d+)?\s*%")
NOT_GROWN = re.compile(r"не\s+(вы)?рос|не\s+подн|не\s+увелич", re.I)
VOLUME = re.compile(r"опира|размеченн|объ[её]м|малом\s+числ|всего\s+\d+\s+отзыв", re.I)
# в «что случилось» улики показывают только совпадение по времени: любая формулировка причины или её отрицания - нарушение
CAUSAL = re.compile(r"из-за|вызвал|привел\w*\s+к|привёл\s+к|в\s+ответ\s+на|мог(ла|ли|ло)?\s+быть\s+связан|связан\w*\s+с|"
                    r"объясня|на\s+фоне|послужил|спровоцир|стал\w*\s+причин|причин\w*", re.I)
LABEL_WORDS = re.compile(r"сфокусирован|размазан|значим|ядр\w*\s+сдвиг|главная\s+категория|направлени\w*\s+(ухудшение|улучшение)", re.I)
COMPLAINT_WORD = re.compile(r"жалоб|критик", re.I)
PAIR = re.compile(r"(\d+)\s*%\s*(?:до|->|→|-)\s*(\d+)\s*%|с\s+(\d+)\s*%\s+до\s+(\d+)\s*%")


def foreign_letters(text):
    """Буквы вне кириллицы и латиницы: иероглифы, кана, хангыль и прочие письменности, скопированные из отзывов-опор."""
    return sorted({ch for ch in text if unicodedata.category(ch).startswith("L")
                   and not unicodedata.name(ch, "").startswith(("LATIN", "CYRILLIC"))})


def parse(raw):
    """(what_happened, what_players_say) из JSON-ответа; (None, None), если JSON не тот."""
    data = load_json(raw)
    if not isinstance(data, dict) or not all(isinstance(data.get(f), str) and data[f].strip() for f in FIELDS):
        return None, None
    return data["what_happened"].strip(), data["what_players_say"].strip()


def sentences(text):
    return [x for x in re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\[])", text.strip()) if x.strip()]


def refs(text):
    return [int(x) for m in REF.finditer(text) for x in m.group(1).split(",")]


def votes_as_complaints(text, votes_pair):
    """Пара чисел до/после рядом со словом «жалобы/критика» совпадает с долей оценок «не рекомендую» - метрики перепутаны."""
    if votes_pair is None:
        return False
    for m in PAIR.finditer(text):
        nums = tuple(int(x) for x in m.groups() if x is not None)
        if nums == votes_pair and COMPLAINT_WORD.search(text[max(0, m.start() - 80):m.start()]):
            return True
    return False


def check(raw, labels, votes_pair, known_numbers, vocab):
    """Проверки кодом. labels - ярлыки точки (news, character, volume, main_diff). Вернуть (замечания, what, talk)."""
    what, talk = parse(raw)
    if what is None:
        return [f"не JSON с полями {', '.join(FIELDS)}"], None, None
    problems = []
    for m in CAUSAL.finditer(what):
        problems.append(f"what_happened: формулировка причины «{m.group(0)}»")
    if REF.search(what):
        problems.append("what_happened: номера отзывов")
    for m in LABEL_WORDS.finditer(what):
        problems.append(f"what_happened: служебный ярлык «{m.group(0)}»")
    for sent in sentences(what):
        # «с 14% до 11%» порядок задаёт сама; иначе у пары должны быть и «до», и «после» («2% до, 8% после»)
        rest = FROM_TO.sub("", sent)
        if NUMBER_PAIR.search(rest) and not (re.search(r"\bдо\b", rest) and re.search(r"\bпосле\b", rest)):
            problems.append(f"what_happened: пара чисел без «до» и «после» «{sent[:60]}…»")
    if labels["main_diff"] is not None and labels["main_diff"] > 0 and NOT_GROWN.search(what):
        problems.append("what_happened: «не вырос / не поднялся» при росте главной темы")
    if labels["volume"] == "достаточный" and VOLUME.search(what):
        problems.append("what_happened: упоминание объёма при достаточном объёме")
    if votes_as_complaints(what, votes_pair):
        problems.append("what_happened: доля «не рекомендую» названа жалобами/критикой")
    if re.search(r"повод", what + " " + talk, re.I) and (labels["news"] == "нет" or labels["character"] == "сфокусированный"):
        problems.append("«повод» при отсутствии новостей или сфокусированном характере")
    for part, text in (("what_happened", what), ("what_players_say", talk)):
        # вывод пишется по-русски; из других языков допустимы только собственные названия латиницей (Battle.net, Vessel of Hatred)
        letters = foreign_letters(text)
        if letters:
            problems.append(f"{part}: буквы не кириллицы и не латиницы «{''.join(letters)}»")
        for m in SNAKE.finditer(text):
            problems.append(f"{part}: id справочника «{m.group(0)}»")
        for name in vocab:
            if re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", text.lower()):
                problems.append(f"{part}: английское название «{name}»")
    for sent in sentences(talk):
        found = refs(sent)
        if not found:
            problems.append(f"what_players_say: утверждение без опоры «{sent[:60]}…»")
        bad = sorted(set(found) - set(known_numbers))
        if bad:
            problems.append(f"what_players_say: номера не из улик {bad}")
    return problems, what, talk
