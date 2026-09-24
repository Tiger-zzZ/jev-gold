"""V2 出图：概率分桶、基准率、命中率对比。只算数，不画图、不碰网络。"""
from __future__ import annotations

import unittest

from jev_gold.calibration_chart import MIN_N, base_rate, bucket_series, hit_rates


def row(pred, label, probs, day="2024-01-03"):
    return {
        "date": day,
        "pred_1d": pred,
        "label_1d": label,
        "pred_5d": pred,
        "label_5d": label,
        "probs_5d": probs,
    }


class BucketTests(unittest.TestCase):
    def test_avg_prob_n_freq(self):
        rows = [row("up", "up", {"up": 0.9, "down": 0.05, "flat": 0.05}) for _ in range(10)]
        rows += [row("up", "down", {"up": 0.3, "down": 0.5, "flat": 0.2}) for _ in range(12)]
        series = bucket_series(rows, "up")
        self.assertEqual(len(series), 2)
        high = next(s for s in series if s[0] > 0.5)
        self.assertAlmostEqual(high[0], 0.9)
        self.assertEqual(high[1], 10)
        self.assertAlmostEqual(high[2], 1.0)

    def test_thin_bucket_dropped(self):
        # 15 个样本落在 0.8+ 桶，但只有 3 个在 0.4–0.6，后者该被丢掉
        rows = [row("up", "up", {"up": 0.85, "down": 0.1, "flat": 0.05}) for _ in range(15)]
        rows += [row("flat", "up", {"up": 0.5, "down": 0.2, "flat": 0.3}) for _ in range(MIN_N - 7)]
        series = bucket_series(rows, "up")
        self.assertEqual(len(series), 1)  # 0.4–0.6 桶样本不够，丢了
        self.assertAlmostEqual(series[0][0], 0.85)

    def test_ignores_rows_without_five_day_label(self):
        rows = [row("up", "up", {"up": 0.9, "down": 0.05, "flat": 0.05}) for _ in range(MIN_N)]
        rows.append({"date": "2026-09-16", "pred_5d": "down", "label_5d": None,
                     "probs_5d": {"up": 0.1, "down": 0.8, "flat": 0.1}})
        series = bucket_series(rows, "up")
        self.assertEqual(series[0][1], MIN_N)  # 没标签的那行没算进去


class BaseRateTests(unittest.TestCase):
    def test_share(self):
        rows = [row("up", "up", {}), row("up", "down", {}), row("up", "up", {}), row("up", "flat", {})]
        self.assertAlmostEqual(base_rate(rows, "up", "5d"), 0.5)

    def test_skips_unlabeled(self):
        rows = [row("up", "up", {}), {"date": "2026-09-16", "label_5d": None}]
        self.assertAlmostEqual(base_rate(rows, "up", "5d"), 1.0)


class HitRateTests(unittest.TestCase):
    def test_jev_first_and_order_fixed(self):
        rows = [row("up", "up", {"up": 0.9, "down": 0.05, "flat": 0.05}) for _ in range(8)]
        rows += [row("flat", "down", {"up": 0.3, "down": 0.3, "flat": 0.4}) for _ in range(2)]
        rates = hit_rates(rows, "5d")
        self.assertEqual(rates[0][0], "Jev")
        self.assertEqual([r[0] for r in rates],
                         ["Jev", "always_up", "always_flat", "always_down", "momentum_5d", "momentum_20d"])
        self.assertEqual(rates[0][1:3], (8, 10))
        self.assertIsNotNone(rates[0][3])  # Jev 有 Wilson 区间
        self.assertIsNone(rates[1][3])     # 基线不给区间

    def test_always_up_counts_all_up_labels(self):
        rows = [row("down", "up", {}) for _ in range(6)] + [row("up", "down", {}) for _ in range(4)]
        rates = {r[0]: (r[1], r[2]) for r in hit_rates(rows, "5d")}
        self.assertEqual(rates["always_up"], (6, 10))
        self.assertEqual(rates["always_down"], (4, 10))

    def test_horizons_use_their_own_labeled_rows(self):
        rows = [{"date": "d1", "pred_1d": "up", "label_1d": "up", "pred_5d": "up", "label_5d": None}]
        self.assertEqual(hit_rates(rows, "1d")[0][1:3], (1, 1))
        self.assertEqual(hit_rates(rows, "5d")[0][2], 0)  # 5d 没有可标注样本


if __name__ == "__main__":
    unittest.main()
