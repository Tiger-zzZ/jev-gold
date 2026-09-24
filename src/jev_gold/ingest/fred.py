"""FRED 宏观数据。无 key 时整体降级为 None，不阻塞管线。"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

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


# ---------- v2 评测：全历史一次拉取，本地切片 ----------

FRED_CACHE = Path(".cache/fred")


def series_history(api_key: str, series_id: str, start: str = "2021-01-01") -> dict[str, float]:
    """整条序列（升序 date->value），带本地缓存，避免 240 窗逐次打 API。"""
    cache = FRED_CACHE / f"{series_id}.json"
    if cache.exists():
        return {k: float(v) for k, v in json.loads(cache.read_text()).items()}
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    resp = requests.get(FRED_OBS, params=params, timeout=30)
    resp.raise_for_status()
    series = {
        obs["date"]: float(obs["value"])
        for obs in resp.json().get("observations", [])
        if obs.get("value") not in (None, ".")
    }
    FRED_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(series))
    return series


def level_at(series: dict[str, float], day: date) -> float | None:
    """最后一个 ≤ day 的观测值（FRED 周末/节假日不发数）。"""
    stamp = day.isoformat()
    keys = [k for k in series if k <= stamp]
    return series[max(keys)] if keys else None


def change_20d(series: dict[str, float], day: date) -> float | None:
    """约 20 个交易日的变化量（用 28 个自然日近似，两端都取最近观测）。"""
    now, then = level_at(series, day), level_at(series, day - timedelta(days=28))
    if now is None or then is None:
        return None
    return round(now - then, 4)
