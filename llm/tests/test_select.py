import unittest
from datetime import date

from llm.select import day_order, plan

D1, D2 = date(2026, 9, 1), date(2026, 9, 2)


def row(rid, day=D1, length=100, status=None):
    return {"recommendation_id": rid, "day": day, "length": length, "status": status}


class PlanTest(unittest.TestCase):
    def test_short_reviews_go_to_too_short_outside_limit(self):
        p = plan([row(1, length=5), row(2, length=19), row(3, length=20)], min_length=20, day_limit=1)
        self.assertEqual([r["recommendation_id"] for r in p["too_short"]], [1, 2])
        self.assertEqual([r["recommendation_id"] for r in p["to_label"]], [3])

    def test_known_too_short_not_repeated_but_retried_after_threshold_drop(self):
        rows = [row(1, length=10, status="too_short"), row(2, length=15, status="too_short")]
        p = plan(rows, min_length=20, day_limit=30)
        self.assertEqual((p["too_short"], p["short_known"]), ([], 2))
        p = plan(rows, min_length=12, day_limit=30)
        self.assertEqual([r["recommendation_id"] for r in p["to_label"]], [2])
        self.assertEqual(p["retry"], 1)

    def test_day_limit_by_md5_order_per_day(self):
        rows = [row(i) for i in range(10)] + [row(i, day=D2) for i in range(100, 105)]
        p = plan(rows, min_length=20, day_limit=3)
        first_day = sorted(range(10), key=day_order)[:3]
        self.assertEqual([r["recommendation_id"] for r in p["to_label"] if r["day"] == D1], first_day)
        self.assertEqual([r["day_rank"] for r in p["to_label"] if r["day"] == D1], [1, 2, 3])
        self.assertEqual(p["over_limit"], 7 + 2)

    def test_order_does_not_depend_on_input_order(self):
        rows = [row(i) for i in range(20)]
        a = plan(rows, 20, 5)["to_label"]
        b = plan(list(reversed(rows)), 20, 5)["to_label"]
        self.assertEqual(a, b)

    def test_raising_limit_adds_only_new(self):
        rows = [row(i) for i in range(10)]
        first = {r["recommendation_id"] for r in plan(rows, 20, 3)["to_label"]}
        labeled = [row(r["recommendation_id"], status="labeled" if r["recommendation_id"] in first else None)
                   for r in rows]
        second = plan(labeled, 20, 5)
        self.assertEqual(second["done"], 3)
        self.assertEqual(len(second["to_label"]), 2)
        self.assertFalse(first & {r["recommendation_id"] for r in second["to_label"]})

    def test_failed_retried_done_skipped(self):
        p = plan([row(1, status="failed"), row(2, status="no_opinion"), row(3, status="labeled")], 20, 30)
        self.assertEqual([r["recommendation_id"] for r in p["to_label"]], [1])
        self.assertEqual((p["done"], p["retry"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
