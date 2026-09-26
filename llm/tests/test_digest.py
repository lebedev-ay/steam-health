import json
import unittest

from llm.digest import as_text, check, known_numbers, next_month, prev_month
from datetime import date

EV = {
    "month": "2026-06-01",
    "reviews": {"now": 3716, "prev": 3467},
    "positive_share": {"now": 0.74, "prev": 0.83},
    "labeled": {"now": 900, "prev": 930},
    "categories": [{"id": "technical_performance", "name": "Technical performance",
                    "critique": 0.18, "critique_prev": 0.09, "praise": 0.02, "praise_prev": 0.03}],
    "aspects": [{"id": "stability", "name": "Stability", "critique": 0.12, "critique_prev": 0.05,
                 "praise": 0.01, "praise_prev": 0.01}],
    "new_topics": [{"note": "save corruption", "n": 7}],
    "news": [{"date": "2026-06-21", "title": "Patch 0.219.10", "type": "patch", "weight": 4.2}],
    "turning_points": [{"date": "2026-06-19", "shift_pp": -14.4}],
}
VOCAB = ["Technical performance", "Stability"]


def answer(headline="Вылеты вернулись: жалобы на стабильность выросли до 12%",
           summary="Доля положительных отзывов упала с 83% до 74%. Жалобы на вылеты - с 5% до 12%. В том же месяце вышел патч 0.219.10."):
    return json.dumps({"headline": headline, "summary": summary}, ensure_ascii=False)


class DigestCheckTest(unittest.TestCase):
    def test_good_answer_passes(self):
        problems, headline, _ = check(answer(), EV, VOCAB)
        self.assertEqual(problems, [])
        self.assertTrue(headline.startswith("Вылеты"))

    def test_invented_number_flagged(self):
        problems, _, _ = check(answer(summary="Доля положительных отзывов - 70%."), EV, VOCAB)
        self.assertTrue(any("70%" in p for p in problems))

    def test_difference_between_months_is_known(self):
        self.assertIn(9, known_numbers(EV))          # 83% -> 74%
        self.assertEqual(check(answer(summary="Позитив упал на 9% за месяц."), EV, VOCAB)[0], [])

    def test_cause_ids_and_english_names_flagged(self):
        problems, _, _ = check(answer(summary="Из-за патча выросли жалобы на stability и Technical performance."), EV, VOCAB)
        self.assertTrue(any("причины" in p for p in problems))
        self.assertTrue(any("английское название" in p for p in problems))

    def test_not_json(self):
        self.assertEqual(check("просто текст", EV, VOCAB)[0], ["не JSON с полями headline и summary"])

    def test_long_headline_flagged(self):
        self.assertTrue(check(answer(headline="Очень " * 30), EV, VOCAB)[0])

    def test_text_has_numbers_news_and_points(self):
        text = as_text("Valheim", EV)
        for part in ("74%", "83%", "12%", "Patch 0.219.10", "-14.4 п.п.", "save corruption - 7", "июнь 2026"):
            self.assertIn(part, text)

    def test_month_arithmetic(self):
        self.assertEqual(next_month(date(2026, 12, 1)), date(2027, 1, 1))
        self.assertEqual(prev_month(date(2026, 1, 1)), date(2025, 12, 1))


if __name__ == "__main__":
    unittest.main()
