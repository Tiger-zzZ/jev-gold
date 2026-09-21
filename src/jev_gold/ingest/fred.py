"""FRED 宏观数据。无 key 时整体降级为 None，不阻塞管线。"""
from __future__ import annotations

import requests

FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"

# DFII10: 10Y TIPS 实际利率（金价核心宏观因子）
# DTWEXBGS: 广义美元指数（DXY 的免费替代）
SERIES = {"real_yield_10y": "DFII10", "dollar_index": "DTWEXBGS"}


def _latest_value(series_id: str, api_key: str, as_of: str | None = None) -> float | None:
    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": "15",
    }
    if as_of:
        params["observation_end"] = as_of
    resp = requests.get(FRED_OBS, params=params, timeout=20)
    resp.raise_for_status()
    for obs in resp.json().get("observations", []):
        if obs.get("value") not in (None, "."):
            return float(obs["value"])
    return None


def macro_snapshot(api_key: str | None, as_of: str | None = None) -> dict[str, float | None]:
    if not api_key:
        return {name: None for name in SERIES}
    out: dict[str, float | None] = {}
    for name, sid in SERIES.items():
        try:
            out[name] = _latest_value(sid, api_key, as_of=as_of)
        except Exception:
            out[name] = None  # 单系列失败不影响其他
    return out
