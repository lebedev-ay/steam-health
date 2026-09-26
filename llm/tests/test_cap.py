import sys
import unittest
from contextlib import redirect_stderr
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from llm.label import parse_args
from llm.select import cap

D = date(2026, 9, 1)


def item(rid, day_offset, rank=1, app_id=1):
    return {"recommendation_id": rid, "day": D + timedelta(days=day_offset), "day_rank": rank, "app_id": app_id}


class CapTest(unittest.TestCase):
    def test_fresh_days_first_across_games(self):
        items = [item(1, 0, app_id=1), item(2, 5, app_id=2), item(3, 3, app_id=1), item(4, 5, rank=2, app_id=1)]
        taken, left = cap(items, 3)
        self.assertEqual([r["recommendation_id"] for r in taken], [2, 4, 3])
        self.assertEqual(left, 1)

    def test_under_limit_takes_everything(self):
        items = [item(i, i) for i in range(10)]
        taken, left = cap(items, 5000)
        self.assertEqual((len(taken), left), (10, 0))

    def test_next_run_continues_where_previous_stopped(self):
        # размеченное следующий запуск не видит: в его план попадают только оставшиеся
        items = [item(i, i % 7, rank=i) for i in range(12)]
        first, left = cap(items, 5)
        rest = [r for r in items if r not in first]
        second, left2 = cap(rest, 5)
        third, left3 = cap([r for r in rest if r not in second], 5)
        self.assertEqual((left, left2, left3), (7, 2, 0))
        self.assertEqual(len({r["recommendation_id"] for r in first + second + third}), 12)

    def test_zero_limit_stops_immediately(self):
        taken, left = cap([item(1, 0)], 0)
        self.assertEqual((taken, left), ([], 1))


class ArgsTest(unittest.TestCase):
    def parse(self, *argv):
        with mock.patch.object(sys, "argv", ["label", *argv]):
            return parse_args()

    def test_all_enabled_has_cap_and_adaptive(self):
        args = self.parse("--all-enabled")
        self.assertEqual((args.cap, args.adaptive), (5000, True))
        self.assertEqual(self.parse("--all-enabled", "--max-per-run", "300").cap, 300)

    def test_manual_app_id_has_no_cap(self):
        args = self.parse("--app-id", "892970", "--max-per-run", "10")
        self.assertIsNone(args.cap)
        self.assertFalse(args.adaptive)

    def test_all_enabled_rejects_period(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            self.parse("--all-enabled", "--since", "2026-01-01")


if __name__ == "__main__":
    unittest.main()
