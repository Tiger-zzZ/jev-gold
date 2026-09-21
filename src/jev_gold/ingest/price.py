"""金价快照：GC=F（COMEX 期金）小时线，失败回退 GLD 日线。PoC 用延迟数据足够。"""
from __future__ import annotations


def _pct(now: float, then: float) -> float | None:
    if then == 0:
        return None
    return round((now / then - 1.0) * 100.0, 3)


def gold_snapshot() -> dict[str, float | str | None]:
    import yfinance as yf  # 延迟导入：yfinance 加载慢，且便于单测替换

    try:
        hist = yf.Ticker("GC=F").history(period="7d", interval="1h")
        closes = hist["Close"].dropna()
        if len(closes) >= 2:
            last = float(closes.iloc[-1])
            # 24h 前的最近一个点（小时线约每交易小时一根）
            past_24h = float(closes.iloc[-25]) if len(closes) >= 25 else float(closes.iloc[0])
            first_7d = float(closes.iloc[0])
            return {
                "symbol": "GC=F",
                "last": round(last, 2),
                "change_24h_pct": _pct(last, past_24h),
                "change_7d_pct": _pct(last, first_7d),
                "as_of": str(closes.index[-1]),
            }
    except Exception:
        pass

    try:  # 回退：GLD 日线
        hist = yf.Ticker("GLD").history(period="7d", interval="1d")
        closes = hist["Close"].dropna()
        if len(closes) >= 2:
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            return {
                "symbol": "GLD",
                "last": round(last, 2),
                "change_24h_pct": _pct(last, prev),
                "change_7d_pct": _pct(last, float(closes.iloc[0])),
                "as_of": str(closes.index[-1]),
            }
    except Exception:
        pass

    return {"symbol": None, "last": None, "change_24h_pct": None, "change_7d_pct": None, "as_of": None}
