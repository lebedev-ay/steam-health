import json
import unittest

from llm.check import batch_text, parse

ALLOWED = {"stability", "pricing_fairness", "overall_impression"}


def answer(*items):
    return json.dumps([{"n": n, "aspects": aspects} for n, aspects in items])


class ParseTest(unittest.TestCase):
    def test_clean_batch(self):
        results, errors = parse(answer(
            (1, [{"id": "stability", "sentiment": "-"}]),
            (2, []),
        ), 2, ALLOWED)
        self.assertEqual(errors, [])
        self.assertEqual(results, {1: [{"id": "stability", "sentiment": "-", "note": None}], 2: []})

    def test_code_fence_is_stripped(self):
        content = "```json\n" + answer((1, [{"id": "stability", "sentiment": "±"}])) + "\n```"
        results, errors = parse(content, 1, ALLOWED)
        self.assertEqual(errors, [])
        self.assertEqual(results[1][0]["sentiment"], "±")

    def test_not_json_and_not_list(self):
        self.assertEqual(parse("Sure! Here you go", 1, ALLOWED), ({}, ["ответ не JSON"]))
        self.assertEqual(parse('{"n": 1}', 1, ALLOWED), ({}, ["ответ не массив"]))

    def test_numbers_must_be_exactly_1_to_n(self):
        results, errors = parse(answer(
            (1, []), (1, []), (3, []), (True, []),
        ), 2, ALLOWED)
        self.assertEqual(list(results), [1])
        self.assertIn("пропущен номер: 2", errors)
        self.assertEqual(sum(e.startswith("лишний или повторный") for e in errors), 3)

    def test_unknown_id_rejects_whole_review(self):
        # модель выдумывает id вне справочника - главная причина отказов в разведке
        results, errors = parse(answer(
            (1, [{"id": "stability", "sentiment": "-"}, {"id": "core_loop", "sentiment": "-"}]),
        ), 1, ALLOWED)
        self.assertEqual(results, {})
        self.assertTrue(errors[0].startswith("n=1: кривые аспекты"))
        self.assertNotIn("пропущен номер: 1", errors)

    def test_bad_sign(self):
        results, _ = parse(answer((1, [{"id": "stability", "sentiment": "neutral"}])), 1, ALLOWED)
        self.assertEqual(results, {})

    def test_other_needs_short_note(self):
        ok, _ = parse(answer((1, [{"id": "other", "note": " Game Loop ", "sentiment": "-"}])), 1, ALLOWED)
        self.assertEqual(ok[1], [{"id": "other", "sentiment": "-", "note": "game loop"}])
        for note in (None, "", "one two three four"):
            results, _ = parse(answer((1, [{"id": "other", "note": note, "sentiment": "-"}])), 1, ALLOWED)
            self.assertEqual(results, {}, note)

    def test_duplicates_dropped_other_with_different_notes_kept(self):
        results, _ = parse(answer((1, [
            {"id": "stability", "sentiment": "-"},
            {"id": "stability", "sentiment": "+"},
            {"id": "other", "note": "a", "sentiment": "-"},
            {"id": "other", "note": "b", "sentiment": "-"},
            {"id": "other", "note": "a", "sentiment": "+"},
        ])), 1, ALLOWED)
        self.assertEqual([(a["id"], a["note"], a["sentiment"]) for a in results[1]],
                         [("stability", None, "-"), ("other", "a", "-"), ("other", "b", "-")])

    def test_more_than_five_keeps_first_five(self):
        aspects = [{"id": "other", "note": f"topic {i}", "sentiment": "-"} for i in range(7)]
        results, errors = parse(answer((1, aspects)), 1, ALLOWED)
        self.assertEqual(errors, [])
        self.assertEqual([a["note"] for a in results[1]], [f"topic {i}" for i in range(5)])

    def test_batch_text_numbers_from_one(self):
        self.assertEqual(batch_text(["a", "b"]), '<review n="1">a</review>\n<review n="2">b</review>')


if __name__ == "__main__":
    unittest.main()
