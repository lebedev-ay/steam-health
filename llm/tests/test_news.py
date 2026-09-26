import json
import unittest

from llm.news import batch_text, clean, parse

ITEMS = [{"date": "2026-06-21", "game": "Valheim", "title": "Patch 0.219.10", "body": "[h1]Combat[/h1] rebalance"},
         {"date": "2026-06-22", "game": "Valheim", "title": "Summer sale", "body": "-50%"}]


def answer(*objs):
    return json.dumps(list(objs), ensure_ascii=False)


GOOD = {"n": 1, "tier": "major", "kind": "balance", "future": False, "title_ru": "Патч 0.219.10: переделка боя"}


class CleanTest(unittest.TestCase):
    def test_strips_steam_markup_images_and_links(self):
        raw = ("[h1]Big update[/h1][img]{STEAM_CLAN_IMAGE}/1/a.png[/img] New <b>biome</b>! "
               "[url=https://x.y]Read more[/url] https://store.steampowered.com/app/1")
        self.assertEqual(clean(raw), "Big update New biome ! Read more")

    def test_cuts_on_word_boundary(self):
        self.assertEqual(clean("один два три четыре", 12), "один два…")

    def test_batch_numbers_items_and_keeps_meta(self):
        text = batch_text(ITEMS)
        self.assertIn('<news n="1" date="2026-06-21" game="Valheim">Patch 0.219.10\nCombat rebalance</news>', text)
        self.assertIn('<news n="2"', text)


class ParseTest(unittest.TestCase):
    def test_good_answer(self):
        results, errors = parse(answer(GOOD, {**GOOD, "n": 2, "tier": "background", "kind": "sale",
                                              "title_ru": "Летняя распродажа"}), 2)
        self.assertEqual(errors, [])
        self.assertEqual(results[1], {"tier": "major", "kind": "balance", "is_future": False,
                                      "title_ru": "Патч 0.219.10: переделка боя"})

    def test_bad_item_rejects_only_itself(self):
        results, errors = parse(answer(GOOD, {**GOOD, "n": 2, "tier": "huge"}), 2)
        self.assertIn(1, results)
        self.assertNotIn(2, results)
        self.assertTrue(any("tier" in e for e in errors))

    def test_title_checks(self):
        for title, why in (("A" * 41, "длиной"), ("Season 7", "без русских"), ("Сезон 季", "не кириллицы")):
            results, errors = parse(answer({**GOOD, "title_ru": title}), 1)
            self.assertNotIn(1, results, title)
            self.assertTrue(any(why in e for e in errors), (title, errors))

    def test_title_trimmed_of_quotes_and_period(self):
        results, _ = parse(answer({**GOOD, "title_ru": "«Сезон 7»."}), 1)
        self.assertEqual(results[1]["title_ru"], "Сезон 7")

    def test_future_must_be_boolean(self):
        results, errors = parse(answer({**GOOD, "future": "no"}), 1)
        self.assertEqual(results, {})

    def test_missing_extra_and_duplicate_numbers(self):
        results, errors = parse(answer(GOOD, GOOD, {**GOOD, "n": 5}), 2)
        self.assertEqual(list(results), [1])
        self.assertTrue(any("повторный" in e for e in errors))
        self.assertIn("пропущен номер: 2", errors)

    def test_not_json_and_fenced(self):
        self.assertEqual(parse("нет", 1)[1], ["ответ не JSON"])
        self.assertIn(1, parse("```json\n" + answer(GOOD) + "\n```", 1)[0])


if __name__ == "__main__":
    unittest.main()
