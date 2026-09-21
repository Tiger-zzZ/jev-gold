"""门控契约：Jev 出判断，代码只执行阈值。"""
from __future__ import annotations

import unittest

from jev_gold.gate import CONFIDENCE_THRESHOLD, FLAT, HOLD, LONG, decide
from jev_gold.judge import JudgeResult


def _result(direction: str, conf: float, risk: int | None) -> JudgeResult:
    return JudgeResult(
        raw={},
        geopolitical_risk=risk,
        geopolitical_risk_confidence=0.9,
        news_direction=direction,
        news_direction_confidence=conf,
        news_direction_probabilities={direction: conf},
        fed_repricing=0.2,
    )


class GateTests(unittest.TestCase):
    def test_bullish_high_conf_and_risk_goes_long(self):
        action, reason = decide(_result("bullish_gold", 0.80, 1))
        self.assertEqual(action, LONG)
        self.assertIn("risk=1", reason)

    def test_bullish_high_conf_but_risk_zero_holds(self):
        action, _ = decide(_result("bullish_gold", 0.99, 0))
        self.assertEqual(action, HOLD)

    def test_bearish_high_conf_goes_flat(self):
        action, _ = decide(_result("bearish_gold", 0.80, 0))
        self.assertEqual(action, FLAT)

    def test_just_below_threshold_holds(self):
        action, _ = decide(_result("bullish_gold", CONFIDENCE_THRESHOLD - 0.01, 3))
        self.assertEqual(action, HOLD)

    def test_neutral_always_holds(self):
        action, _ = decide(_result("neutral", 0.99, 3))
        self.assertEqual(action, HOLD)

    def test_missing_risk_does_not_long(self):
        action, _ = decide(_result("bullish_gold", 0.95, None))
        self.assertEqual(action, HOLD)


if __name__ == "__main__":
    unittest.main()
