"""FOMC 日历必须覆盖回测事件日，否则 days_to_next_fomc 会污染 Jev state。"""
from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from jev_gold.backtest import EVENTS
from jev_gold.state import FOMC_STATEMENT_DATES, _days_to_next_fomc, build_state


class FomcCalendarTests(unittest.TestCase):
    def test_event_windows_have_sane_days_to_next_fomc(self):
        for ev in EVENTS:
            day = date.fromisoformat(ev["date"])
            days = _days_to_next_fomc(day)
            self.assertIsNotNone(days, msg=f"{ev['id']} {ev['date']} 超出日历")
            self.assertLessEqual(days, 60, msg=f"{ev['id']} days_to_next_fomc={days} 像缺日期")

    def test_fomc_event_days_are_statement_dates(self):
        for ev in EVENTS:
            if ev["kind"] != "fomc":
                continue
            self.assertIn(date.fromisoformat(ev["date"]), FOMC_STATEMENT_DATES, ev["id"])

    def test_known_invasion_and_oct7_offsets(self):
        self.assertEqual(_days_to_next_fomc(date(2022, 2, 24)), 20)  # 2022-03-16
        self.assertEqual(_days_to_next_fomc(date(2023, 10, 7)), 25)  # 2023-11-01
        self.assertEqual(_days_to_next_fomc(date(2022, 3, 16)), 0)


class BuildStateTests(unittest.TestCase):
    def test_now_override_drives_fomc_offset(self):
        now = datetime(2022, 2, 24, 18, 0, tzinfo=timezone.utc)
        state = build_state({}, [], {}, {}, now=now)
        self.assertEqual(state["macro"]["days_to_next_fomc"], 20)
        self.assertEqual(state["asset"], "gold (COMEX GC=F front month, USD)")


if __name__ == "__main__":
    unittest.main()
