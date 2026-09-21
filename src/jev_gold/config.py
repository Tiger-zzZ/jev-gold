"""集中配置：全部走环境变量，缺省即降级（macro=None / mock judge）。"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    fred_api_key: str | None
    jev_api_key: str | None
    jev_base_url: str | None
    jev_model: str
    db_path: str
    judge_backend: str  # "mock" | "jev"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            fred_api_key=os.environ.get("FRED_API_KEY") or None,
            jev_api_key=os.environ.get("JEV_API_KEY") or None,
            jev_base_url=os.environ.get("JEV_BASE_URL") or "https://ai-gateway.vercel.sh",
            jev_model=os.environ.get("JEV_MODEL", "typesafe-ai/jev"),
            db_path=os.environ.get("JEV_GOLD_DB", "jev_gold.db"),
            judge_backend=os.environ.get("JEV_GOLD_JUDGE", "mock"),
        )
