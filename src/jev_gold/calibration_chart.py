"""V2 周频实验的两张图：概率校准曲线 + 命中率对比。

读 reports/weekly_eval.json（先跑 `python -m jev_gold.weekly_eval` 生成），写 docs/calibration_chart.png。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .weekly_eval import BASELINES, _label, wilson

CLASSES = ("up", "down", "flat")
NAMES = {"up": "涨", "down": "跌", "flat": "横盘"}
COLORS = {"up": "#1a9850", "down": "#d73027", "flat": "#7a7a7a"}
EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
MIN_N = 10  # 少于这个数不画点，避免两三个样本撑出一个假趋势
FORECASTERS = ["Jev", "always_up", "always_flat", "always_down", "momentum_5d", "momentum_20d"]


def bucket_series(rows: list[dict[str, Any]], cls: str) -> list[tuple[float, int, float, float, float]]:
    """按 Jev 自报的 P(cls) 分桶。

    返回 [(平均报的概率, n, 实际频率, Wilson 下界, Wilson 上界), ...]，样本不足的桶丢掉。
    """
    out = []
    for lo_edge, hi_edge in zip(EDGES, EDGES[1:]):
        sel = [r for r in rows if lo_edge <= r["probs_5d"].get(cls, -1.0) < hi_edge]
        if len(sel) < MIN_N:
            continue
        avg = sum(r["probs_5d"][cls] for r in sel) / len(sel)
        hits = sum(1 for r in sel if r["label_5d"] == cls)
        ci = wilson(hits, len(sel))
        out.append((avg, len(sel), hits / len(sel), ci[0], ci[1]))
    return out


def base_rate(rows: list[dict[str, Any]], cls: str, horizon: str) -> float:
    labels = [r[f"label_{horizon}"] for r in rows if r.get(f"label_{horizon}")]
    return sum(1 for x in labels if x == cls) / len(labels)


def hit_rates(rows: list[dict[str, Any]], horizon: str) -> list[tuple[str, int, int, tuple[float, float] | None]]:
    """返回 [(预测者, 命中数, 标注样本数, Wilson 区间), ...]，按 FORECASTERS 的顺序，第一项是 Jev。"""
    labeled = [r for r in rows if r.get(f"label_{horizon}")]
    n = len(labeled)

    def hits(predict) -> int:
        return sum(1 for r in labeled if predict(r) == r[f"label_{horizon}"])

    out = []
    for name in FORECASTERS:
        if name == "Jev":
            k = hits(lambda r: r[f"pred_{horizon}"])
            out.append((name, k, n, wilson(k, n)))
        elif name in BASELINES:
            out.append((name, hits(BASELINES[name]), n, None))
        else:  # always_<sign>：永远报同一个方向
            sign = name.split("_", 1)[1]
            out.append((name, hits(lambda r, s=sign: s), n, None))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="plot V2 calibration + hit-rate comparison")
    parser.add_argument("--report", default="reports/weekly_eval.json")
    parser.add_argument("--out", default="docs/calibration_chart.png")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    rows = json.loads(Path(args.report).read_text())
    rows_5d = [r for r in rows if r.get("label_5d")]  # 校准图按 5 日标签算，命中率对比各自取各自的可标注样本
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})

    # 左：校准曲线。对角线是"说多少就是多少"，Jev 的三条线应该贴着它才对。
    ax1.plot([0, 1], [0, 1], ls="--", lw=1, color="#999999", zorder=1)
    ax1.annotate("说多少就是多少", (0.62, 0.66), fontsize=9, color="#888888", rotation=34)
    for cls in CLASSES:
        series = bucket_series(rows_5d, cls)
        if not series:
            continue
        xs = [p[0] for p in series]
        ys_ = [p[2] for p in series]
        err = [[p[2] - p[3] for p in series], [p[4] - p[2] for p in series]]
        ax1.errorbar(xs, ys_, yerr=err, color=COLORS[cls], lw=1.6, marker="o", ms=5,
                     capsize=3, elinewidth=0.9, label=f"P({NAMES[cls]})")
        br = base_rate(rows_5d, cls, "5d")
        ax1.axhline(br, color=COLORS[cls], ls=":", lw=1, alpha=0.45)
        for x, y, n in [(p[0], p[2], p[1]) for p in series]:
            ax1.annotate(f"n={n}", (x, y), textcoords="offset points", xytext=(0, -14),
                         ha="center", fontsize=7, color=COLORS[cls])
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.set_xlabel("Jev 报的概率")
    ax1.set_ylabel("实际发生的频率")
    ax1.set_title("它报的概率 vs 实际结果", fontsize=11)
    ax1.legend(loc="upper left", frameon=False, fontsize=9)
    ax1.text(0.02, 0.02, "虚线 = 基准率（无信息时的水平）", fontsize=8, color="#999999", transform=ax1.transAxes)
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.grid(alpha=0.2)

    # 右：命中率 vs 基线，1 日和 5 日各一组。Jev 排最上面，一眼就能跟基线比。
    names = [h[0] for h in hit_rates(rows, "5d")][::-1]
    ys = list(range(len(names)))
    for offset, horizon, color in ((-0.19, "1d", "#8fb8de"), (0.19, "5d", "#2b6cb0")):
        rates = hit_rates(rows, horizon)[::-1]
        ax2.barh([y + offset for y in ys], [r[1] / r[2] for r in rates], height=0.36,
                 color=color, label=horizon)
        for y, (_, k, n, ci) in zip(ys, rates):
            rate = k / n
            # 数值标签放在置信区间右端之外，免得压在区间线上
            x = max(rate, ci[1] if ci else rate) + 0.012
            ax2.text(x, y + offset, f"{rate:.0%}", va="center", fontsize=8, color="#444444")
            if ci:
                ax2.plot([ci[0], ci[1]], [y + offset, y + offset], color="#1a202c", lw=1.2)
    ax2.set_yticks(list(ys))
    ax2.set_yticklabels(names, fontsize=9)
    ax2.set_xlim(0, 0.85)
    ax2.set_xlabel("命中率")
    ax2.set_title("Jev vs 什么都不想的基线", fontsize=11)
    ax2.axvline(base_rate(rows, "up", "5d"), color="#bbbbbb", lw=1, ls=":", zorder=0)
    ax2.legend(loc="lower right", frameon=False, fontsize=9)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.grid(axis="x", alpha=0.2)

    fig.suptitle("V2：244 个周频窗口（2022-01 ~ 2026-09），灰棒是 Jev 的 95% 置信区间", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
