"""发布门：event_study.json 必须覆盖全部事件，且 FOMC 偏移不能再被旧日历污染。"""
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from jev_gold.backtest import EVENTS
from jev_gold.state import _days_to_next_fomc


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "reports" / "event_study.json"


class PublishedStudyTests(unittest.TestCase):
    def test_all_real_jev_windows_with_sane_fomc(self):
        self.assertTrue(STUDY.exists(), "run python -m jev_gold.backtest first")
        rows = json.loads(STUDY.read_text())
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(set(by_id), {e["id"] for e in EVENTS})
        for ev in EVENTS:
            row = by_id[ev["id"]]
            self.assertTrue(row.get("jev_ok"), ev["id"])
            expected = _days_to_next_fomc(date.fromisoformat(ev["date"]))
            self.assertEqual(row.get("days_to_next_fomc"), expected, ev["id"])
            self.assertIn(row.get("direction"), {"bullish_gold", "bearish_gold", "neutral"})
            self.assertIn(row.get("gate"), {"long", "flat", "hold"})


if __name__ == "__main__":
    unittest.main()
