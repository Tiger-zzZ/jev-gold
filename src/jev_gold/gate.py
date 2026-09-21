"""置信度门控 v1：Jev 出判断，这里出行动。

规则（与 task_plan.md 决策契约一致）：
- news_direction=bullish 且 confidence≥0.8 且 geopolitical_risk≥1 → long
- news_direction=bearish 且 confidence≥0.8 → flat
- 其余 → hold（不动仓，仅记录）
"""
from __future__ import annotations

from .judge import JudgeResult

CONFIDENCE_THRESHOLD = 0.8
RISK_FLOOR = 1

LONG, FLAT, HOLD = "long", "flat", "hold"


def decide(result: JudgeResult) -> tuple[str, str]:
    direction = result.news_direction
    conf = result.news_direction_confidence or 0.0
    risk = result.geopolitical_risk if result.geopolitical_risk is not None else -1

    if direction == "bullish_gold" and conf >= CONFIDENCE_THRESHOLD:
        if risk >= RISK_FLOOR:
            return LONG, f"bullish({conf:.2f}) + risk={risk} ≥ {RISK_FLOOR}"
        return HOLD, f"bullish({conf:.2f}) 但风险等级 {risk} < {RISK_FLOOR}，不动仓"
    if direction == "bearish_gold" and conf >= CONFIDENCE_THRESHOLD:
        return FLAT, f"bearish({conf:.2f}) → 清仓观望"
    return HOLD, f"低置信或中性（direction={direction}, conf={conf:.2f}），不动仓"
