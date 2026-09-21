"""回测标签与报告：方向命中、分桶、GDELT 缺失不调用 Jev。"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from jev_gold.backtest import EVENTS, _bucket, _direction_hit, _write_md, run
from jev_gold.config import Config
from jev_gold.ingest.gdelt import pulse_from_zip_bytes
from jev_gold.judge import MockJudge


class DirectionHitTests(unittest.TestCase):
    def test_bullish_up_is_hit(self):
        self.assertEqual(_direction_hit("bullish_gold", 1.2), "hit")

    def test_bullish_down_is_miss(self):
        self.assertEqual(_direction_hit("bullish_gold", -0.2), "miss")

    def test_tiny_move_is_neutral_actual(self):
        self.assertEqual(_direction_hit("bullish_gold", 0.10), "miss")
        self.assertEqual(_direction_hit("neutral", 0.10), "neutral_call")

    def test_neutral_call_excluded_from_directional(self):
        self.assertEqual(_direction_hit("neutral", 2.0), "neutral_call")

    def test_none_passthrough(self):
        self.assertIsNone(_direction_hit(None, 1.0))
        self.assertIsNone(_direction_hit("bullish_gold", None))


class BucketTests(unittest.TestCase):
    def test_edges(self):
        self.assertEqual(_bucket(0.0), "0.00–0.40")
        self.assertEqual(_bucket(0.399), "0.00–0.40")
        self.assertEqual(_bucket(0.4), "0.40–0.60")
        self.assertEqual(_bucket(0.6), "0.60–0.80")
        self.assertEqual(_bucket(0.8), "0.80–1.00")
        self.assertIsNone(_bucket(None))


class PulseParserTests(unittest.TestCase):
    def test_conflict_share_from_synthetic_zip(self):
        # 58-col TSV: root@28, goldstein@30, mentions@31, tone@34
        def row(root: str, goldstein: str, mentions: str, tone: str) -> str:
            cols = [""] * 40
            cols[28], cols[30], cols[31], cols[34] = root, goldstein, mentions, tone
            return "\t".join(cols)

        tsv = "\n".join(
            [
                row("19", "-9.0", "10", "-2.0"),  # fight / conflict
                row("04", "4.0", "3", "1.0"),     # cooperate
            ]
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("20220224.export.CSV", tsv)
        pulse = pulse_from_zip_bytes(buf.getvalue(), "test")
        self.assertEqual(pulse["events_total"], 2)
        self.assertEqual(pulse["conflict_events"], 1)
        self.assertEqual(pulse["conflict_share"], 0.5)
        self.assertEqual(pulse["goldstein_mean_conflict"], -9.0)
        self.assertEqual(pulse["fight_events"], 1)


class WriteMdTests(unittest.TestCase):
    def test_hit_rate_excludes_neutral_and_skips(self):
        rows = [
            {"jev_ok": True, "hit_1d": "hit", "hit_5d": "miss", "direction_conf": 0.5,
             "date": "2022-02-24", "kind": "geo", "direction": "bullish_gold",
             "risk": 3, "gate": "hold", "fwd_1d_pct": 1.0, "conflict_share": 0.2},
            {"jev_ok": True, "hit_1d": "neutral_call", "hit_5d": "neutral_call", "direction_conf": 0.2,
             "date": "2022-09-26", "kind": "geo", "direction": "neutral",
             "risk": 2, "gate": "hold", "fwd_1d_pct": 0.2, "conflict_share": 0.1},
            {"jev_ok": False, "hit_1d": None, "hit_5d": None, "direction_conf": None,
             "date": "2023-01-01", "kind": "geo", "direction": None,
             "risk": None, "gate": "hold", "fwd_1d_pct": None, "conflict_share": None},
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "event_study.md"
            _write_md(path, rows, "mock")
            text = path.read_text()
        self.assertIn("1/1 = 100%", text)
        self.assertIn("开仓次数: 0", text)
        self.assertIn("| 0.40–0.60 | 1 | 1 |", text)
        self.assertIn("| 0.80–1.00 | 0 | 0 |", text)


class SkipJevWhenPulseMissingTests(unittest.TestCase):
    def test_missing_pulse_does_not_call_judge(self):
        called = {"n": 0}

        class CountingJudge(MockJudge):
            def evaluate(self, state):
                called["n"] += 1
                return super().evaluate(state)

        cfg = Config(
            fred_api_key=None,
            jev_api_key=None,
            jev_base_url=None,
            jev_model="mock",
            db_path=":memory:",
            judge_backend="mock",
        )
        import pandas as pd

        idx = pd.date_range("2022-02-20", periods=20, freq="D")
        closes = pd.Series(range(100, 120), index=idx, dtype=float)
        one = [EVENTS[0]]
        with tempfile.TemporaryDirectory() as td:
            with patch("jev_gold.backtest.EVENTS", one), \
                 patch("jev_gold.backtest._gold_history", return_value=("GLD", closes)), \
                 patch("jev_gold.backtest.make_judge", return_value=CountingJudge()), \
                 patch("jev_gold.ingest.gdelt.conflict_pulse_for_date", side_effect=RuntimeError("no zip")), \
                 patch("jev_gold.ingest.fred.macro_snapshot", return_value={"real_yield_10y": None, "dollar_index": None}):
                run(cfg, Path(td), resume=False)
            row = json.loads((Path(td) / "event_study.json").read_text())[0]
        self.assertEqual(called["n"], 0)
        self.assertFalse(row["jev_ok"])
        self.assertEqual(row["gate"], "hold")
        self.assertIn("skip_jev", row["gate_reason"])


if __name__ == "__main__":
    unittest.main()
