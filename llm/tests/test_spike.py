import unittest
from datetime import date, timedelta

from llm.select import SPIKE_WINDOW, day_limits, plan

START = date(2025, 1, 1)
PARAMS = {"day_limit": 30, "spike_factor": 2, "spike_min_abs": 60, "spike_limit": 200}


def series(values, start=START):
    return {start + timedelta(days=i): n for i, n in enumerate(values)}


class SpikeTest(unittest.TestCase):
    def test_first_window_days_never_spike(self):
        limits = day_limits(series([10] * (SPIKE_WINDOW - 1) + [1000]), **PARAMS)
        last = START + timedelta(days=SPIKE_WINDOW - 1)
        self.assertIsNone(limits[last]["median"])
        self.assertEqual((limits[last]["spike"], limits[last]["limit"]), (False, 30))

    def test_spike_needs_factor_and_min_abs(self):
        day = START + timedelta(days=SPIKE_WINDOW)
        for n, spike in [(100, True), (99, False), (60, False)]:
            limits = day_limits(series([50] * SPIKE_WINDOW + [n]), **PARAMS)
            self.assertEqual(limits[day]["median"], 50)
            self.assertEqual(limits[day]["spike"], spike, n)
            self.assertEqual(limits[day]["limit"], 200 if spike else 30)
        # вдвое выше медианы, но ниже абсолютного порога - не всплеск
        limits = day_limits(series([20] * SPIKE_WINDOW + [59]), **PARAMS)
        self.assertFalse(limits[day]["spike"])
        limits = day_limits(series([20] * SPIKE_WINDOW + [60]), **PARAMS)
        self.assertTrue(limits[day]["spike"])

    def test_missing_days_count_as_zero(self):
        # отзывы раз в неделю: медиана по календарным дням - ноль, решает абсолютный порог
        content = {START + timedelta(days=i): 70 for i in range(0, 60, 7)}
        limits = day_limits(content, **PARAMS)
        late = [d for d in content if d >= START + timedelta(days=SPIKE_WINDOW)]
        self.assertTrue(all(limits[d]["median"] == 0 and limits[d]["spike"] for d in late))

    def test_current_day_not_in_its_median(self):
        day = START + timedelta(days=SPIKE_WINDOW)
        limits = day_limits(series([10] * SPIKE_WINDOW + [500, 10]), **PARAMS)
        self.assertEqual(limits[day]["median"], 10)
        # на следующий день всплеск уже в окне, но медиану 28 дней одна точка не сдвигает
        self.assertEqual(limits[day + timedelta(days=1)]["median"], 10)

    def test_empty(self):
        self.assertEqual(day_limits({}, **PARAMS), {})


class PlanWithLimitsTest(unittest.TestCase):
    def rows(self, n, day=START, status=None):
        return [{"recommendation_id": i, "day": day, "length": 100, "status": status} for i in range(n)]

    def test_spike_day_takes_spike_limit_other_days_normal(self):
        other = START + timedelta(days=1)
        rows = self.rows(250) + [{**r, "recommendation_id": r["recommendation_id"] + 1000, "day": other}
                                 for r in self.rows(250)]
        p = plan(rows, 20, 30, {START: 200})
        per_day = {d: sum(r["day"] == d for r in p["to_label"]) for d in (START, other)}
        self.assertEqual(per_day, {START: 200, other: 30})

    def test_raising_limit_on_spike_adds_only_next_ranks(self):
        rows = self.rows(250)
        first = plan(rows, 20, 30)["to_label"]
        done = {r["recommendation_id"] for r in first}
        again = plan([{**r, "status": "labeled" if r["recommendation_id"] in done else None} for r in rows],
                     20, 30, {START: 200})
        self.assertEqual(again["done"], 30)
        self.assertEqual(len(again["to_label"]), 170)
        self.assertEqual(sorted(r["day_rank"] for r in again["to_label"]), list(range(31, 201)))
        self.assertFalse(done & {r["recommendation_id"] for r in again["to_label"]})


if __name__ == "__main__":
    unittest.main()
