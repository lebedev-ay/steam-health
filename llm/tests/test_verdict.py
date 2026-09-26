import json
import unittest
from datetime import date

from llm.verdict_check import check, evidence_hash, excerpt_text, excerpts, status

LABELS = {"news": "есть", "character": "сфокусированный", "volume": "достаточный", "main_diff": 0.12}
VOTES = (11, 14)
VOCAB = ["Monetization and value", "pricing_fairness"]
GOOD_WHAT = "Доля оценок «не рекомендую» выросла с 11% до 14% после 23 мая. Жалобы на цену - 2% до и 14% после. 20 мая вышла заметка разработчиков."
GOOD_TALK = "Игроки возмущены подорожанием игры в раннем доступе [1, 5]. Из-за роста цены многие советуют ждать скидки [7]."


def answer(what=GOOD_WHAT, talk=GOOD_TALK):
    return json.dumps({"what_happened": what, "what_players_say": talk}, ensure_ascii=False)


def run(raw, labels=LABELS):
    return check(raw, labels, VOTES, {1, 5, 7, 8}, VOCAB)[0]


class HashTest(unittest.TestCase):
    EV = {"app_id": 1, "labels": {"direction": "ухудшение", "focus": 0.57},
          "reviews": [{"number": 1, "votes_up": 10, "text": "дорого"}]}

    def test_stable_regardless_of_key_order(self):
        reordered = json.loads(json.dumps({k: self.EV[k] for k in reversed(list(self.EV))}))
        self.assertEqual(evidence_hash(self.EV), evidence_hash(reordered))

    def test_votes_up_does_not_change_hash_text_does(self):
        more_votes = {**self.EV, "reviews": [{**self.EV["reviews"][0], "votes_up": 999}]}
        other_text = {**self.EV, "reviews": [{**self.EV["reviews"][0], "text": "дёшево"}]}
        self.assertEqual(evidence_hash(self.EV), evidence_hash(more_votes))
        self.assertNotEqual(evidence_hash(self.EV), evidence_hash(other_text))

    def test_labeling_config_changes_hash(self):
        self.assertNotEqual(evidence_hash({**self.EV, "labeling_config_sk": 4}),
                            evidence_hash({**self.EV, "labeling_config_sk": 5}))


class StatusTest(unittest.TestCase):
    def test_final_after_window_plus_late_reviews(self):
        at = date(2025, 5, 23)
        self.assertEqual(status(at, date(2025, 6, 1)), "preliminary")   # дата + 9
        self.assertEqual(status(at, date(2025, 6, 2)), "final")         # дата + 10
        self.assertEqual(status(at, date(2026, 1, 1)), "final")


class ExcerptTest(unittest.TestCase):
    def test_cut_on_word_boundary(self):
        text = "Игра хорошая, но цена " + "очень " * 40 + "высокая"
        cut = excerpt_text(text)
        self.assertLessEqual(len(cut), 150)
        self.assertTrue(cut.endswith("…"))
        self.assertTrue(text.startswith(cut[:-1]))
        self.assertIn(cut[:-1].split()[-1], ("очень", "цена"))

    def test_short_text_kept_and_whitespace_folded(self):
        self.assertEqual(excerpt_text("Дорого.\n\nНе  берите"), "Дорого. Не берите")

    def test_top_votes_among_support_only(self):
        reviews = {1: {"votes_up": 5, "text": "a"}, 2: {"votes_up": 500, "text": "b"},
                   3: {"votes_up": 50, "text": "c"}, 4: {"votes_up": 9, "text": "d"}, 9: {"votes_up": 10_000, "text": "не опора"}}
        got = excerpts([1, 2, 3, 4, 4], reviews)
        self.assertEqual([e["number"] for e in got], [2, 3, 4])
        self.assertNotIn("recommendation_id", got[0])


class CheckTest(unittest.TestCase):
    def test_good_answer_passes(self):
        self.assertEqual(run(answer()), [])

    def test_not_json(self):
        self.assertTrue(run("Что случилось: ...")[0].startswith("не JSON"))
        self.assertTrue(run(json.dumps({"what_happened": "x"}))[0].startswith("не JSON"))

    def test_cause_forbidden_only_in_what_happened(self):
        problems = run(answer(what=GOOD_WHAT + " Рост связан с новостью."))
        self.assertTrue(any("формулировка причины" in p for p in problems))
        # «из-за» во второй части - пересказ мотивов игроков, это разрешено
        self.assertEqual(run(answer()), [])

    def test_review_numbers_rules(self):
        self.assertTrue(any("номера отзывов" in p for p in run(answer(what=GOOD_WHAT + " [1]"))))
        self.assertTrue(any("без опоры" in p for p in run(answer(talk="Игроки возмущены ценой. Жалуются на скидки [7]."))))
        self.assertTrue(any("не из улик" in p for p in run(answer(talk="Игроки возмущены ценой [42]."))))

    def test_ids_english_names_and_labels(self):
        self.assertTrue(any("id справочника" in p for p in run(answer(talk="Жалобы на pricing_fairness [1]."))))
        self.assertTrue(any("английское название" in p for p in run(answer(what=GOOD_WHAT.replace("на цену", "на Monetization and value")))))
        self.assertTrue(any("служебный ярлык" in p for p in run(answer(what=GOOD_WHAT + " Рост размазан по темам."))))

    def test_pair_needs_before_and_after(self):
        what = "Доля оценок «не рекомендую» выросла с 11% до 14% после 23 мая. Жалобы на цену: 2% против 14%."
        self.assertTrue(any("без «до» и «после»" in p for p in run(answer(what=what))))

    def test_votes_named_as_complaints(self):
        what = "Жалобы выросли с 11% до 14% после 23 мая, 20 мая вышла заметка."
        self.assertTrue(any("не рекомендую» названа" in p for p in run(answer(what=what))))

    def test_occasion_only_when_spread_with_news(self):
        what = GOOD_WHAT + " Новость - повод."
        self.assertTrue(any("повод" in p for p in run(answer(what=what))))
        spread = {**LABELS, "character": "размазанный"}
        self.assertFalse(any("повод" in p for p in run(answer(what=what), spread)))


if __name__ == "__main__":
    unittest.main()
