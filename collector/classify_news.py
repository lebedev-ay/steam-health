import re
import psycopg
from psycopg.rows import dict_row

from db import DSN

PATTERNS = [
    # --- будущее время: анонс, не событие ---
    (r'\b(coming|arrives?|arriving|releases? (date|schedule)|launch (date|times?))\b', "announce"),
    (r'\b(next week|next month|soon|upcoming|preview|pre-?(purchase|order|load))\b',   "announce"),
    (r'\b(until|before) \b',                                                            "announce"),
    (r'\bmark your calendars?\b',                                                       "announce"),

    # --- маркетинг ---
    (r'\b(sale|discount|% off|bundle|deal)\b',                          "marketing"),
    (r'\b(twitch drops?|lootbox|loot hunt|giveaway|xp (bonus|boost|weekend))\b', "marketing"),
    (r'\b(trailer|cinematic|livestream|spotlight|animated short)\b',    "marketing"),
    (r'\b(contest|nominate|awards?|anniversary|celebrat)\w*\b',         "marketing"),
    (r'\b(collab|crossover|\bx\b .*(pack|dlc|bundle))\b',               "marketing"),
    (r'\b(warbond|cosmetic|skin|plush|merch|trading cards)\b',          "marketing"),
    (r'\b(million (players|sold)|surpasses|\d+[km]?\+? (sold|players|members|reviews))\b', "marketing"),

    # --- блоги и коммуникация, не патч ---
    (r'\bthis week in\b',                                               "blog"),
    (r"\bdirector'?s take\b",                                           "blog"),
    (r'\bdev(eloper)?\'?s? (update|insights?|diary|blog|stream|team)\b', "blog"),
    (r'\bword from the devs\b',                                         "blog"),
    (r'\bdevelopment blog\b',                                           "blog"),
    (r'\b(community update \d+)\b',                                     "blog"),
    (r'\b(roadmap|status update|town hall|state of the game|tech blog)\b', "blog"),
    (r'\b(letter from|transmission from|note (from|on))\b',             "blog"),

    # --- служебное ---
    (r'\b(maintenance|delay|delist|survey)\b',                          "service"),

    # --- события ---
    (r'\bseason \d+.*\b(now live|is here|is now live|begins)\b',        "season_start"),
    (r'\bmidseason\b',                                                  "patch"),
    (r'\bexpansion\b.*\b(available|out now|live)\b',                    "expansion"),
    (r'\b(patch|release|update|hotfix) notes?\b',                       "patch"),
    (r'\b(hotfix|changelog)\b',                                         "patch"),
    (r'\b(patch|update|hotfix)\s*#?\s*\d',                              "patch"),
]

VERSION_RE = re.compile(r'(?:^|\s|[vV#])(\d+\.\d+(?:\.\d+)*)')
BETA_RE = re.compile(r'\b(public test|experimental|exp|beta|test branch|b\d+)\b', re.IGNORECASE)
STABLE_RE = re.compile(r'\b(stable|public branch)\b', re.IGNORECASE)
FALSE_VERSION_RE = re.compile(r'\d+[\.,]?\d*\s*(million|k\+|m\+|%|years?|players|sold)', re.IGNORECASE)

COMPILED = [(re.compile(p, re.IGNORECASE), kind) for p, kind in PATTERNS]


def extract_version(title):
    if FALSE_VERSION_RE.search(title):
        return None
    match = VERSION_RE.search(title)
    if not match:
        return None
    version = match.group(1)
    if int(version.split('.')[0]) > 100:
        return None
    return version

def version_weight(version):
    """Крупность релиза по номеру: 3 мажорный, 2 минорный, 1 мелкий."""
    if not version:
        return None
    parts = version.split('.')
    # ищем последний ненулевой уровень
    last = 0
    for i, p in enumerate(parts):
        if p.strip('0'):
            last = i
    if last == 0:
        return 3
    if last == 1:
        return 2
    return 1

def classify(title):
    version = extract_version(title)

    # бета проверяется до всего, но stable её перебивает
    if BETA_RE.search(title) and not STABLE_RE.search(title):
        return version, "beta"

    for pattern, kind in COMPILED:
        if pattern.search(title):
            return version, kind

    if version:
        return version, "patch"

    return None, "unknown"

from collections import Counter

def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        rows = conn.execute("""
            select distinct item ->> 'gid' as gid, item ->> 'title' as title
            from raw.news n,
                 jsonb_array_elements(n.payload -> 'appnews' -> 'newsitems') as item
            where (item ->> 'feed_type')::int = 1
        """).fetchall()

    counter = Counter()
    for r in rows:
        _, kind = classify(r["title"])
        counter[kind] += 1

    total = sum(counter.values())
    for kind, cnt in counter.most_common():
        print(f"{kind:14} {cnt:5}  {100*cnt/total:5.1f}%")
    print(f"{'ИТОГО':14} {total:5}")

if __name__ == "__main__":
    main()