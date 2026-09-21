"""Judge 解析契约与 mock 确定性。不打真实 Jev。"""
from __future__ import annotations

import unittest

from jev_gold.judge import JevJudge, MockJudge, QUESTIONS, _to_api_questions


class ToApiQuestionsTests(unittest.TestCase):
    def test_score_legend_becomes_criteria(self):
        api = _to_api_questions(QUESTIONS)
        self.assertEqual(api["geopolitical_risk"]["type"], "score")
        self.assertIn("criteria", api["geopolitical_risk"])
        self.assertNotIn("legend", api["geopolitical_risk"])
        self.assertEqual(len(api["geopolitical_risk"]["criteria"]), 4)

    def test_choice_and_noul_pass_through(self):
        api = _to_api_questions(QUESTIONS)
        self.assertEqual(api["news_direction"]["type"], "choice")
        self.assertEqual(set(api["news_direction"]["criteria"]), {"bullish_gold", "bearish_gold", "neutral"})
        self.assertEqual(api["fed_repricing"]["type"], "noul")


class ParseTests(unittest.TestCase):
    def test_parse_rounds_float_score_and_reads_noul(self):
        payload = {
            "answers": {
                "geopolitical_risk": {"score": 2.4, "confidence": 0.81},
                "news_direction": {
                    "choice": "bullish_gold",
                    "confidence": 0.65,
                    "probabilities": {"bullish_gold": 0.65, "bearish_gold": 0.1, "neutral": 0.25},
                },
                "fed_repricing": {"noul": 0.33},
            }
        }
        result = JevJudge._parse(payload)
        self.assertEqual(result.geopolitical_risk, 2)
        self.assertEqual(result.news_direction, "bullish_gold")
        self.assertEqual(result.fed_repricing, 0.33)

    def test_parse_falls_back_to_probability_alias(self):
        payload = {
            "answers": {
                "geopolitical_risk": {"score": 1, "confidence": 0.5},
                "news_direction": {"choice": "neutral", "confidence": 0.4, "probabilities": {}},
                "fed_repricing": {"probability": 0.12},
            }
        }
        result = JevJudge._parse(payload)
        self.assertEqual(result.fed_repricing, 0.12)


class MockJudgeTests(unittest.TestCase):
    def test_same_state_is_deterministic(self):
        state = {"as_of": "2022-02-24T18:00:00+00:00", "conflict_news_pulse": {"conflict_share": 0.19}}
        a = MockJudge().evaluate(state)
        b = MockJudge().evaluate(state)
        self.assertEqual(a.news_direction, b.news_direction)
        self.assertEqual(a.geopolitical_risk, b.geopolitical_risk)
        self.assertEqual(a.fed_repricing, b.fed_repricing)
        self.assertIn(a.news_direction, QUESTIONS["news_direction"]["criteria"])
        self.assertIn(a.geopolitical_risk, (0, 1, 2, 3))


if __name__ == "__main__":
    unittest.main()
