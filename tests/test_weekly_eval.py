"""v2 周频评测：标签口径、基线、Wilson 区间、mock 全链路 smoke。不打真实 Jev。"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from jev_gold.config import Config
from jev_gold.weekly_eval import (
    N_COMPARISONS,
    _hit,
    _label,
    _slice_mask,
    baseline_always_up,
    baseline_momentum_5d,
    run,
    wednesdays,
    wilson,
)


class LabelTests(unittest.TestCase):
    def test_flat_band(self):
        self.assertEqual(_label(1.5), "up")
        self.assertEqual(_label(-1.5), "down")
        self.assertEqual(_label(0.99), "flat")
        self.assertEqual(_label(1.0), "flat")
        self.assertIsNone(_label(None))

    def test_hit_passthrough(self):
        self.assertIsNone(_hit(None, "up"))
        self.assertIsNone(_hit("up", None))
        self.assertTrue(_hit("up", "up"))
        self.assertFalse(_hit("up", "down"))


class WednesdayTests(unittest.TestCase):
    def test_all_wednesdays_in_range(self):
        days = wednesdays()
        self.assertTrue(all(d.weekday() == 2 for d in days))
        self.assertEqual(days[0], date(2022, 1, 5))
        self.assertEqual(days[-1], date(2026, 9, 16))
        self.assertGreater(len(days), 200)


class BaselineTests(unittest.TestCase):
    def test_always_up(self):
        self.assertEqual(baseline_always_up({}), "up")

    def test_momentum_uses_past_return(self):
        self.assertEqual(baseline_momentum_5d({"ret_5d": 2.0}), "up")
        self.assertEqual(baseline_momentum_5d({"ret_5d": -2.0}), "down")
        self.assertEqual(baseline_momentum_5d({"ret_5d": 0.3}), "flat")
        self.assertIsNone(baseline_momentum_5d({"ret_5d": None}))


class WilsonTests(unittest.TestCase):
    def test_known_value(self):
        lo, hi = wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=2)
        self.assertAlmostEqual(hi, 0.7635, places=2)

    def test_zero_n(self):
        self.assertIsNone(wilson(0, 0))


class SliceTests(unittest.TestCase):
    def test_masks(self):
        rows = [
            {"conf_5d": 0.7, "pulse_conflict_share": 0.2, "risk": 3, "macro_real_yield_10y_chg_20d": 0.1},
            {"conf_5d": 0.3, "pulse_conflict_share": 0.1, "risk": 1, "macro_real_yield_10y_chg_20d": -0.1},
        ]
        self.assertEqual(len(_slice_mask("conf_ge_0.6", rows, 0.15)), 1)
        self.assertEqual(len(_slice_mask("high_conflict", rows, 0.15)), 1)
        self.assertEqual(len(_slice_mask("risk_ge_2", rows, 0.15)), 1)
        self.assertEqual(len(_slice_mask("real_yield_rising", rows, 0.15)), 1)
        self.assertEqual(len(_slice_mask("all", rows, 0.15)), 2)


class RunSmokeTests(unittest.TestCase):
    def test_mock_end_to_end(self):
        idx = pd.date_range("2022-01-03", periods=60, freq="B")
        closes = pd.Series([100.0 + i for i in range(60)], index=idx)
        pulse = {
            "events_total": 1000, "conflict_share": 0.19,
            "goldstein_mean_conflict": -7.5, "avgtone_mean_all": -2.0,
        }
        cfg = Config(
            fred_api_key=None, jev_api_key=None, jev_base_url=None,
            jev_model="mock", db_path=":memory:", judge_backend="mock",
        )
        with tempfile.TemporaryDirectory() as td:
            with patch("jev_gold.weekly_eval.wednesdays", return_value=[date(2022, 2, 23)]), \
                 patch("jev_gold.weekly_eval._gold_history", return_value=("GLD", closes)), \
                 patch("jev_gold.weekly_eval.gdelt.conflict_pulse_for_date", return_value=pulse), \
                 patch("jev_gold.weekly_eval.time.sleep"):
                run(cfg, Path(td), resume=False)
            rows = json.loads((Path(td) / "weekly_eval.json").read_text())
            md = (Path(td) / "weekly_eval.md").read_text()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["jev_ok"])
        self.assertIn(row["pred_5d"], {"up", "down", "flat"})
        self.assertEqual(row["label_5d"], "up")  # 合成价格单调上涨
        self.assertIsNotNone(row["hit_5d"])
        self.assertIn(f"共 {N_COMPARISONS} 组", md)


if __name__ == "__main__":
    unittest.main()
