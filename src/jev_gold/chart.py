"""把事件窗口画在 GLD 价格线上：点的颜色是 Jev 的方向，大小是把握。

读 reports/event_study.json（先跑 backtest 生成），写 docs/event_chart.png。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# 想在点上写清的窗口（其余只留点，避免糊在一起）
LABELS = {
    "ua_invasion": "俄乌开战\n看多 .68",
    "fomc_2022_06_75bp": "+75bp\n看空 .71",
    "svb": "SVB\n看多 .22",
    "hamas_oct7": "哈马斯\n看多 .62",
    "fomc_2024_09_50bp": "降息50bp\n看多 .49",
    "fomc_2026_09": "加息25bp\n看空 .61",
}

COLORS = {"bullish_gold": "#1a9850", "bearish_gold": "#d73027", "neutral": "#878787"}
NAMES = {"bullish_gold": "看多", "bearish_gold": "看空", "neutral": "中性"}


def main() -> int:
    parser = argparse.ArgumentParser(description="plot event windows on GLD price")
    parser.add_argument("--study", default="reports/event_study.json")
    parser.add_argument("--out", default="docs/event_chart.png")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import yfinance as yf

    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    rows = json.loads(Path(args.study).read_text())
    closes = None
    for symbol in ("GLD", "GC=F"):  # yfinance 偶发抽风，和回测一样留后路
        hist = yf.Ticker(symbol).history(start="2022-01-01", interval="1d")
        closes = hist["Close"].dropna()
        if not closes.empty:
            break
    if closes is None or closes.empty:
        raise RuntimeError("yfinance 取不到 GLD/GC=F 价格")
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)

    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(closes.index, closes.values, lw=1.1, color="#444444", zorder=1)

    for r in rows:
        direction = r.get("direction")
        if not r.get("jev_ok") or direction not in COLORS:
            continue
        day = pd.Timestamp(r["date"])
        price = float(closes.asof(day))
        conf = r.get("direction_conf") or 0.0
        ax.scatter(day, price, s=28 + 130 * conf, color=COLORS[direction], zorder=5,
                   edgecolors="white", linewidths=0.6)
        if r["id"] in LABELS:
            ax.annotate(LABELS[r["id"]], (day, price), textcoords="offset points",
                        xytext=(0, 14), ha="center", fontsize=8, color="#333333")

    for direction, color in COLORS.items():
        ax.scatter([], [], color=color, s=60, label=NAMES[direction])
    ax.scatter([], [], color="#bbbbbb", s=30, label="点越大 = 把握越高")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.set_ylabel("GLD（美元）")
    ax.set_title("Jev 对 22 个历史时刻的判断（2022-02 ~ 2026-09）", fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
