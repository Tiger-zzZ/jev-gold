"""v2 周频方向预测评测：问题和标签严格对齐，和傻瓜基线对比。

v1 事件研究的教训：问"新闻流方向"却拿金价当标签，题不对版，n=9 也撑不起结论。
v2 的做法：
- 每周三取样（2022-01 ~ 2026-09，约 240 窗）
- 直接问"未来 1/5 个交易日 GLD 涨超 1% / 跌超 1% / 横盘"（与标签同一口径）
- 对照基线：永远看多、5 日动量、20 日动量
- 报 Wilson 95% 置信区间；环境切分全部预先登记，多重比较数量如实披露

用法：JEV_GOLD_JUDGE=jev python -m jev_gold.weekly_eval --resume
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .backtest import _gold_history
from .config import Config
from .ingest import fred, gdelt
from .judge import QUESTIONS_V2, make_judge
from .loop import _load_dotenv
from .state import _days_to_next_fomc

START = date(2022, 1, 5)       # 2022 年第一个周三
END = date(2026, 9, 16)        # 最后一个有完整 1d 标签的周三
FLAT_BAND_PCT = 1.0
DOWNLOAD_POLITE_S = 0.5

# 预先登记的全部比较（多重比较披露）：2 个 horizon × (整体 + 4 种切分) = 10 组
SLICES = ("all", "conf_ge_0.6", "high_conflict", "risk_ge_2", "real_yield_rising")
N_COMPARISONS = 2 * len(SLICES)


def wednesdays(start: date = START, end: date = END) -> list[date]:
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=7)
    return days


def _label(ret: float | None) -> str | None:
    if ret is None:
        return None
    if ret > FLAT_BAND_PCT:
        return "up"
    if ret < -FLAT_BAND_PCT:
        return "down"
    return "flat"


def _hit(choice: str | None, label: str | None) -> bool | None:
    if choice is None or label is None:
        return None
    return choice == label


def baseline_always_up(_row: dict[str, Any]) -> str:
    return "up"


def baseline_momentum_5d(row: dict[str, Any]) -> str | None:
    return _label(row.get("ret_5d"))


def baseline_momentum_20d(row: dict[str, Any]) -> str | None:
    return _label(row.get("ret_20d"))


BASELINES = {
    "always_up": baseline_always_up,
    "momentum_5d": baseline_momentum_5d,
    "momentum_20d": baseline_momentum_20d,
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """二项比例 Wilson 区间；n=0 返回 None。"""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / denom
    return round(center - margin, 4), round(center + margin, 4)


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1.0) * 100.0, 3)


def _close_at(closes, day: date) -> tuple[int, float] | None:
    """事件日（或之后最近交易日）收盘。返回 (位置索引, 价格)。"""
    import pandas as pd

    pos = closes.index.searchsorted(pd.Timestamp(day))
    if pos >= len(closes):
        return None
    return pos, float(closes.iloc[pos])


def _build_state(day: date, closes, macro_series: dict[str, dict[str, float]]) -> dict[str, Any] | None:
    found = _close_at(closes, day)
    if found is None:
        return None
    pos, last = found
    def back(n: int) -> float | None:
        return float(closes.iloc[pos - n]) if pos - n >= 0 else None

    ry = macro_series.get("real_yield_10y", {})
    dxy = macro_series.get("dollar_index", {})
    return {
        "as_of": f"{day.isoformat()}T18:00:00+00:00",
        "asset": "GLD ETF (USD), proxy for gold spot price",
        "gld_last": round(last, 2),
        "recent_gld_returns_pct": {
            "1d": _pct(last, back(1)),
            "5d": _pct(last, back(5)),
            "20d": _pct(last, back(20)),
        },
        "macro": {
            "real_yield_10y": fred.level_at(ry, day),
            "real_yield_10y_chg_20d": fred.change_20d(ry, day),
            "dollar_index": fred.level_at(dxy, day),
            "dollar_index_chg_20d": fred.change_20d(dxy, day),
            "days_to_next_fomc": _days_to_next_fomc(day),
        },
    }


def _load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {r["date"]: r for r in json.loads(path.read_text()) if r.get("jev_ok")}


def run(cfg: Config, out_dir: Path, resume: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_eval.json"
    existing = _load_existing(json_path) if resume else {}

    _, closes = _gold_history()
    macro_series: dict[str, dict[str, float]] = {}
    if cfg.fred_api_key:
        for name, sid in fred.SERIES.items():
            try:
                macro_series[name] = fred.series_history(cfg.fred_api_key, sid)
            except Exception as exc:
                print(f"[degrade] FRED {sid} 拉取失败：{exc}", file=sys.stderr)
                macro_series[name] = {}

    judge = make_judge(
        cfg.judge_backend,
        api_key=cfg.jev_api_key,
        base_url=cfg.jev_base_url,
        model=cfg.jev_model,
    ) if cfg.judge_backend == "jev" else make_judge("mock")

    days = wednesdays()
    rows: list[dict[str, Any]] = []
    for i, day in enumerate(days):
        key = day.isoformat()
        if key in existing:
            rows.append(existing[key])
            continue
        state = _build_state(day, closes, macro_series)
        if state is None:
            print(f"[{key}] 无价格，跳过", flush=True)
            continue
        try:
            pulse = gdelt.conflict_pulse_for_date(day)
            time.sleep(DOWNLOAD_POLITE_S)
        except Exception as exc:
            print(f"[{key}] GDELT 失败，跳过 Jev：{exc}", file=sys.stderr, flush=True)
            continue
        state["conflict_news_pulse"] = {
            "events_total": pulse.get("events_total"),
            "conflict_share": pulse.get("conflict_share"),
            "goldstein_mean_conflict": pulse.get("goldstein_mean_conflict"),
            "avgtone_mean_all": pulse.get("avgtone_mean_all"),
        }

        pos, _ = _close_at(closes, day)
        last = float(closes.iloc[pos])
        fwd_1d = _pct(float(closes.iloc[pos + 1]), last) if pos + 1 < len(closes) else None
        fwd_5d = _pct(float(closes.iloc[pos + 5]), last) if pos + 5 < len(closes) else None

        try:
            answers = judge.ask(state, QUESTIONS_V2)
            jev_ok = True
        except Exception as exc:
            print(f"[{key}] Jev 失败：{exc}", file=sys.stderr, flush=True)
            answers, jev_ok = {}, False

        d1 = answers.get("fwd_1d_direction", {})
        d5 = answers.get("fwd_5d_direction", {})
        risk = answers.get("geopolitical_risk", {})
        score = risk.get("score")
        row = {
            "date": key,
            "jev_ok": jev_ok,
            "ret_1d": state["recent_gld_returns_pct"]["1d"],
            "ret_5d": state["recent_gld_returns_pct"]["5d"],
            "ret_20d": state["recent_gld_returns_pct"]["20d"],
            "gld_last": state["gld_last"],
            **{f"macro_{k}": v for k, v in state["macro"].items()},
            **{f"pulse_{k}": v for k, v in state["conflict_news_pulse"].items()},
            "risk": None if score is None else int(round(float(score))),
            "pred_1d": d1.get("choice"),
            "conf_1d": d1.get("confidence"),
            "pred_5d": d5.get("choice"),
            "conf_5d": d5.get("confidence"),
            "probs_5d": d5.get("probabilities"),
            "fwd_1d_pct": fwd_1d,
            "fwd_5d_pct": fwd_5d,
            "label_1d": _label(fwd_1d),
            "label_5d": _label(fwd_5d),
            "hit_1d": _hit(d1.get("choice"), _label(fwd_1d)),
            "hit_5d": _hit(d5.get("choice"), _label(fwd_5d)),
        }
        rows.append(row)
        print(f"[{i + 1}/{len(days)}] {key} jev={'ok' if jev_ok else 'FAIL'} "
              f"pred5d={row['pred_5d']}({row['conf_5d']}) label5d={row['label_5d']}", flush=True)
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))

    md_path = out_dir / "weekly_eval.md"
    _write_md(md_path, rows, judge.name)
    print(f"wrote {json_path}\nwrote {md_path}", flush=True)
    return 0


def _slice_mask(name: str, rows: list[dict[str, Any]], median_conflict: float) -> list[dict[str, Any]]:
    if name == "all":
        return rows
    if name == "conf_ge_0.6":
        return [r for r in rows if (r.get("conf_5d") or 0) >= 0.6]
    if name == "high_conflict":
        return [r for r in rows if (r.get("pulse_conflict_share") or 0) >= median_conflict]
    if name == "risk_ge_2":
        return [r for r in rows if (r.get("risk") or 0) >= 2]
    if name == "real_yield_rising":
        return [r for r in rows if (r.get("macro_real_yield_10y_chg_20d") or 0) > 0]
    raise ValueError(name)


def _rate(rows: list[dict[str, Any]], key: str) -> tuple[int, int]:
    ok = [r for r in rows if r.get(key) is not None]
    return sum(1 for r in ok if r[key]), len(ok)


def _write_md(path: Path, rows: list[dict[str, Any]], judge: str) -> None:
    ok_rows = [r for r in rows if r.get("jev_ok")]
    shares = sorted(r["pulse_conflict_share"] for r in ok_rows if r.get("pulse_conflict_share") is not None)
    median_conflict = shares[len(shares) // 2] if shares else 0.0

    lines = [
        "# Jev 周频方向预测评测（v2）",
        "",
        f"- judge: `{judge}`；窗口: {len(rows)}（Jev 成功 {len(ok_rows)}）",
        f"- 标签口径：未来 1/5 个交易日 GLD 收益，±{FLAT_BAND_PCT}% 以内为 flat",
        f"- 多重比较披露：共 {N_COMPARISONS} 组（2 个 horizon × {len(SLICES)} 种切分），切分预先登记",
        "",
        "## 5d 方向命中率 vs 基线",
        "",
        "| 切分 | n | Jev | Wilson 95% | always_up | momentum_5d | momentum_20d |",
        "|---|---|---|---|---|---|---|",
    ]
    for slice_name in SLICES:
        sub = _slice_mask(slice_name, ok_rows, median_conflict)
        k, n = _rate(sub, "hit_5d")
        ci = wilson(k, n)
        cells = []
        for bn, bf in BASELINES.items():
            bk = sum(1 for r in sub if r.get("label_5d") and bf(r) == r["label_5d"])
            bn_ = sum(1 for r in sub if r.get("label_5d"))
            cells.append(f"{bk}/{bn_} ({bk / bn_:.0%})" if bn_ else "–")
        lines.append(
            f"| {slice_name} | {n} | {k}/{n}" + (f" ({k / n:.0%})" if n else "")
            + f" | {f'{ci[0]:.0%}–{ci[1]:.0%}' if ci else '–'} | " + " | ".join(cells) + " |"
        )
    k1, n1 = _rate(ok_rows, "hit_1d")
    ci1 = wilson(k1, n1)
    lines += [
        "",
        f"## 1d 方向命中率（整体）: {k1}/{n1}"
        + (f" ({k1 / n1:.0%})" if n1 else "")
        + (f"，Wilson 95% = {ci1[0]:.0%}–{ci1[1]:.0%}" if ci1 else ""),
        "",
        "注意：相邻周窗口的标签有重叠，有效样本量低于窗口数；以上数字是观察不是绩效。",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev weekly direction-prediction eval (v2)")
    parser.add_argument("--out", default="reports", help="output directory")
    parser.add_argument("--resume", action="store_true", help="reuse jev_ok rows")
    args = parser.parse_args()
    _load_dotenv()
    cfg = Config.from_env()
    return run(cfg, Path(args.out), resume=args.resume)


if __name__ == "__main__":
    raise SystemExit(main())
