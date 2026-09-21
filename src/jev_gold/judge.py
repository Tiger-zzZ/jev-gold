"""判断器：项目的心脏。

Jev 决策契约 v1（冻结于 2026-09-20，改动需评审）：
- geopolitical_risk: Score 0-3，全球冲突/地缘风险当前水平
- news_direction:    Choice，黄金相关新闻流的方向性
- fed_repricing:     Noul，近期新闻是否实质改变美联储政策预期

MockJudge：确定性伪随机（state 哈希做种子），供管线联调；
JevJudge：  真实 HTTP 调用，端点契约待 Phase 0 拿到 key 后核对（见 TODO）。
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

QUESTIONS: dict[str, dict[str, Any]] = {
    "geopolitical_risk": {
        "type": "score",
        "instructions": (
            "Based only on the provided state, rate the current level of "
            "geopolitical conflict risk relevant to safe-haven demand for gold."
        ),
        "legend": [
            "0 = No unusual conflict signal; news flow is routine",
            "1 = Localized tension, within normal range",
            "2 = Clear escalation: new armed conflict, major attack, or sharp rhetoric between states",
            "3 = Major systemic shock: war breakout between significant powers or equivalent",
        ],
    },
    "news_direction": {
        "type": "choice",
        "instructions": (
            "Given the gold headlines, conflict pulse, macro backdrop and recent price "
            "action in state, what is the dominant direction of gold-relevant news flow "
            "right now?"
        ),
        "criteria": {
            "bullish_gold": "News flow on net favors higher gold prices (risk-off, dovish Fed, weak dollar, conflict escalation)",
            "bearish_gold": "News flow on net favors lower gold prices (risk-on, hawkish Fed, strong dollar, de-escalation)",
            "neutral": "Signals are mixed, absent, or offsetting",
        },
    },
    "fed_repricing": {
        "type": "noul",
        "instructions": (
            "Does the recent news flow in state materially change market expectations "
            "for the Federal Reserve policy path (rate cuts/hikes timing or magnitude)?"
        ),
    },
}


@dataclass
class JudgeResult:
    raw: dict[str, Any]
    geopolitical_risk: int | None
    geopolitical_risk_confidence: float | None
    news_direction: str | None
    news_direction_confidence: float | None
    news_direction_probabilities: dict[str, float] = field(default_factory=dict)
    fed_repricing: float | None = None


class Judge(Protocol):
    name: str

    def evaluate(self, state: dict[str, Any]) -> JudgeResult: ...


class MockJudge:
    """确定性占位判断器：同一 state 永远给出同一结果，便于回放与测试。"""

    name = "mock"

    def evaluate(self, state: dict[str, Any]) -> JudgeResult:
        seed = int.from_bytes(
            hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).digest()[:8],
            "big",
        )
        rng = random.Random(seed)

        raw_direction = [rng.random() for _ in QUESTIONS["news_direction"]["criteria"]]
        total = sum(raw_direction)
        probs = {
            k: round(p / total, 4)
            for k, p in zip(QUESTIONS["news_direction"]["criteria"], raw_direction)
        }
        direction = max(probs, key=probs.get)
        risk = rng.randint(0, 3)
        result = {
            "answers": {
                "geopolitical_risk": {"score": risk, "confidence": round(rng.uniform(0.5, 0.99), 4)},
                "news_direction": {
                    "choice": direction,
                    "probabilities": probs,
                    "confidence": round(probs[direction], 4),
                },
                "fed_repricing": {"noul": round(rng.random(), 4)},
            },
            "model": "mock-0",
        }
        return JudgeResult(
            raw=result,
            geopolitical_risk=risk,
            geopolitical_risk_confidence=result["answers"]["geopolitical_risk"]["confidence"],
            news_direction=direction,
            news_direction_confidence=result["answers"]["news_direction"]["confidence"],
            news_direction_probabilities=probs,
            fed_repricing=result["answers"]["fed_repricing"]["noul"],
        )


def _to_api_questions(questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """内部用 legend 描述 Score 等级；TypeSafe HTTP 字段名是 criteria。"""
    out: dict[str, dict[str, Any]] = {}
    for name, q in questions.items():
        item = dict(q)
        if item.get("type") == "score" and "legend" in item and "criteria" not in item:
            item["criteria"] = item.pop("legend")
        out[name] = item
    return out


class JevJudge:
    """真实 Jev 调用：Vercel AI Gateway TypeSafe 兼容端点。

    已核对（2026-09-21）：
    POST {base}/typesafe/v1/systemone
    model = typesafe-ai/jev
    问题类型 noul / choice / score（Gateway 上 yes/no 仍用 noul，不是 boolean）
    """

    name = "jev"

    def __init__(self, api_key: str, base_url: str | None, model: str = "typesafe-ai/jev"):
        if not api_key:
            raise ValueError("JevJudge 需要 JEV_API_KEY")
        self.api_key = api_key
        self.base_url = (base_url or "https://ai-gateway.vercel.sh").rstrip("/")
        self.model = model

    def evaluate(self, state: dict[str, Any]) -> JudgeResult:
        url = f"{self.base_url}/typesafe/v1/systemone"
        body = {
            "model": self.model,
            "state": state,
            "questions": _to_api_questions(QUESTIONS),
        }
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=30,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"Jev HTTP {resp.status_code}: {resp.text[:800]}")
                return self._parse(resp.json())
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Jev call failed after retries: {last_exc}") from last_exc

    @staticmethod
    def _parse(payload: dict[str, Any]) -> JudgeResult:
        answers = payload["answers"]
        risk = answers["geopolitical_risk"]
        direction = answers["news_direction"]
        noul = answers["fed_repricing"]
        score = risk.get("score")
        risk_int = None if score is None else int(round(float(score)))
        fed = noul.get("noul")
        if fed is None:
            fed = noul.get("probability")  # SDK boolean 别名兜底
        return JudgeResult(
            raw=payload,
            geopolitical_risk=risk_int,
            geopolitical_risk_confidence=risk.get("confidence"),
            news_direction=direction.get("choice"),
            news_direction_confidence=direction.get("confidence"),
            news_direction_probabilities=direction.get("probabilities") or {},
            fed_repricing=fed,
        )


def make_judge(backend: str, **kwargs: Any) -> Judge:
    if backend == "jev":
        return JevJudge(**kwargs)
    if backend == "mock":
        return MockJudge()
    raise ValueError(f"未知 judge backend: {backend!r}")
