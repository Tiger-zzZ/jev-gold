"""事件窗口回测：每个窗口一次 Jev 调用（不是全历史 15min 回放）。

对每个事件日：
  GDELT 日频脉搏 + FRED as-of + 金价动量 → Jev 三问 → 门控
  用随后 1d/5d 金价变动做事后标签（方向命中、校准分桶）。

定位：校准与管线验证，不是盈利证明。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .gate import decide
from .ingest import fred, gdelt
from .judge import make_judge
from .loop import _load_dotenv
from .state import build_state

# 每个窗口至多 1 次 Jev。已成功窗口可用 --resume 跳过。
EVENTS: list[dict[str, str]] = [
    {"id": "ua_invasion", "date": "2022-02-24", "kind": "geo",
     "note": "Russia full-scale invasion of Ukraine"},
    {"id": "fomc_2022_03_hike", "date": "2022-03-16", "kind": "fomc",
     "note": "FOMC first hike of cycle"},
    {"id": "fomc_2022_06_75bp", "date": "2022-06-15", "kind": "fomc",
     "note": "FOMC +75bp"},
    {"id": "nord_stream", "date": "2022-09-26", "kind": "geo",
     "note": "Nord Stream explosions"},
    {"id": "svb", "date": "2023-03-10", "kind": "geo",
     "note": "SVB collapse"},
    {"id": "fomc_2023_03", "date": "2023-03-22", "kind": "fomc",
     "note": "FOMC post-SVB"},
    {"id": "quiet_2023_07", "date": "2023-07-12", "kind": "control",
     "note": "Quiet mid-July control"},
    {"id": "hamas_oct7", "date": "2023-10-07", "kind": "geo",
     "note": "Hamas attack on Israel"},
    {"id": "iran_israel_2024", "date": "2024-04-13", "kind": "geo",
     "note": "Iran-Israel direct strike episode"},
    {"id": "fomc_2024_09_50bp", "date": "2024-09-18", "kind": "fomc",
     "note": "FOMC -50bp"},
    {"id": "fomc_2024_11", "date": "2024-11-07", "kind": "fomc",
     "note": "FOMC -25bp"},
    {"id": "fomc_2024_12", "date": "2024-12-18", "kind": "fomc",
     "note": "FOMC -25bp"},
    {"id": "fomc_2025_05", "date": "2025-05-07", "kind": "fomc",
     "note": "FOMC hold"},
    {"id": "quiet_2025_08", "date": "2025-08-15", "kind": "control",
     "note": "Quiet mid-August control (no FOMC)"},
    {"id": "fomc_2025_09", "date": "2025-09-17", "kind": "fomc",
     "note": "FOMC -25bp"},
    {"id": "fomc_2025_10", "date": "2025-10-29", "kind": "fomc",
     "note": "FOMC -25bp"},
    {"id": "fomc_2025_12", "date": "2025-12-10", "kind": "fomc",
     "note": "FOMC -25bp"},
    {"id": "fomc_2026_01", "date": "2026-01-28", "kind": "fomc",
     "note": "FOMC hold"},
    {"id": "fomc_2026_03", "date": "2026-03-18", "kind": "fomc",
     "note": "FOMC hold + SEP"},
    {"id": "fomc_2026_06", "date": "2026-06-17", "kind": "fomc",
     "note": "FOMC hold + SEP"},
]


def _gold_history():
    import yfinance as yf

    # 回测优先 GLD：GC=F 在部分环境会返回 possibly delisted。
    for symbol in ("GLD", "GC=F"):
        hist = yf.Ticker(symbol).history(start="2022-01-01", interval="1d")
        closes = hist["Close"].dropna()
        if not closes.empty:
            closes.index = closes.index.tz_localize(None) if closes.index.tz is not None else closes.index
            closes.index = closes.index.normalize()
            return symbol, closes
    raise RuntimeError("no gold price history from yfinance (GLD/GC=F)")


def _price_at(closes, day: datetime) -> tuple[float | None, Any]:
    idx = closes.index
    on_or_after = idx[idx >= day.replace(hour=0, minute=0, second=0, microsecond=0)]
    if len(on_or_after) == 0:
        return None, None
    ts = on_or_after[0]
    return float(closes.loc[ts]), ts


def _fwd_return(closes, start_ts, days: int) -> float | None:
    if start_ts is None:
        return None
    loc = closes.index.get_loc(start_ts)
    target = loc + days
    if target >= len(closes):
        return None
    a = float(closes.iloc[loc])
    b = float(closes.iloc[target])
    if a == 0:
        return None
    return round((b / a - 1.0) * 100.0, 3)


def _direction_hit(choice: str | None, fwd: float | None) -> str | None:
    if choice is None or fwd is None:
        return None
    if abs(fwd) < 0.15:
        actual = "neutral"
    elif fwd > 0:
        actual = "bullish_gold"
    else:
        actual = "bearish_gold"
    if choice == "neutral":
        return "neutral_call"
    return "hit" if choice == actual else "miss"


def _load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {row["id"]: row for row in data if row.get("jev_ok")}


def run(cfg: Config, out_dir: Path, resume: bool, rerun: set[str] | None = None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "event_study.json"
    existing = _load_existing(json_path) if resume else {}
    rerun = rerun or set()
    symbol, closes = _gold_history()
    judge = make_judge(
        cfg.judge_backend,
        api_key=cfg.jev_api_key,
        base_url=cfg.jev_base_url,
        model=cfg.jev_model,
    ) if cfg.judge_backend == "jev" else make_judge("mock")

    rows: list[dict[str, Any]] = []
    for ev in EVENTS:
        if ev["id"] in existing and ev["id"] not in rerun:
            rows.append(existing[ev["id"]])
            print(f"[{ev['id']}] resume skip (jev_ok)", flush=True)
            continue
        day = datetime.strptime(ev["date"], "%Y-%m-%d")
        print(f"[{ev['id']}] {ev['date']} {ev['kind']} …", flush=True)
        try:
            pulse = gdelt.conflict_pulse_for_date(day)
            pulse_ok = True
        except Exception as exc:
            print(f"  GDELT fail: {exc}", file=sys.stderr, flush=True)
            pulse, pulse_ok = {"source": "missing", "error": str(exc)}, False

        as_of = (day - timedelta(days=1)).strftime("%Y-%m-%d")
        macro = fred.macro_snapshot(cfg.fred_api_key, as_of=as_of)

        last, px_ts = _price_at(closes, day)
        prev_ts = None
        if px_ts is not None:
            loc = closes.index.get_loc(px_ts)
            if loc >= 5:
                prev_ts = closes.index[loc - 5]
        change_5d = None
        if last is not None and prev_ts is not None:
            prev = float(closes.loc[prev_ts])
            change_5d = round((last / prev - 1.0) * 100.0, 3) if prev else None
        price = {
            "symbol": symbol,
            "last": round(last, 2) if last is not None else None,
            "change_24h_pct": None,
            "change_7d_pct": change_5d,
            "as_of": str(px_ts) if px_ts is not None else None,
        }

        now = datetime(day.year, day.month, day.day, 18, 0, tzinfo=timezone.utc)
        state = build_state(pulse, [], macro, price, now=now)
        state["event"] = {"id": ev["id"], "kind": ev["kind"], "note": ev["note"]}

        result = None
        jev_ok = False
        if not pulse_ok:
            action, reason = "hold", "skip_jev: GDELT pulse missing (would contaminate calibration)"
        else:
            try:
                result = judge.evaluate(state)
                action, reason = decide(result)
                jev_ok = True
            except Exception as exc:
                print(f"  Jev fail: {exc}", file=sys.stderr, flush=True)
                action, reason = "hold", f"jev_error:{exc}"

        r1 = _fwd_return(closes, px_ts, 1)
        r5 = _fwd_return(closes, px_ts, 5)
        choice = result.news_direction if result else None
        conf = result.news_direction_confidence if result else None
        row = {
            "id": ev["id"],
            "date": ev["date"],
            "kind": ev["kind"],
            "note": ev["note"],
            "jev_ok": jev_ok,
            "conflict_share": pulse.get("conflict_share"),
            "goldstein": pulse.get("goldstein_mean_conflict"),
            "tone": pulse.get("avgtone_mean_all"),
            "real_yield_10y": macro.get("real_yield_10y"),
            "dollar_index": macro.get("dollar_index"),
            "days_to_next_fomc": state["macro"].get("days_to_next_fomc"),
            "gold_last": price["last"],
            "gold_chg_5d_prior_pct": change_5d,
            "risk": result.geopolitical_risk if result else None,
            "risk_conf": result.geopolitical_risk_confidence if result else None,
            "direction": choice,
            "direction_conf": conf,
            "direction_probs": result.news_direction_probabilities if result else {},
            "fed_repricing": result.fed_repricing if result else None,
            "gate": action,
            "gate_reason": reason,
            "fwd_1d_pct": r1,
            "fwd_5d_pct": r5,
            "hit_1d": _direction_hit(choice, r1),
            "hit_5d": _direction_hit(choice, r5),
            "usage": (result.raw.get("usage") if result else None),
        }
        rows.append(row)
        print(
            f"  jev={choice}({conf}) risk={row['risk']} gate={action} "
            f"fwd1d={r1} hit1d={row['hit_1d']}",
            flush=True,
        )
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))

    csv_path = out_dir / "event_study.csv"
    md_path = out_dir / "event_study.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    _write_csv(csv_path, rows)
    _write_md(md_path, rows, judge.name)
    print(f"wrote {json_path}\nwrote {csv_path}\nwrote {md_path}", flush=True)
    return 0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "id", "date", "kind", "direction", "direction_conf", "risk", "fed_repricing",
        "gate", "fwd_1d_pct", "fwd_5d_pct", "hit_1d", "hit_5d", "conflict_share",
        "real_yield_10y", "dollar_index",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _bucket(conf: float | None) -> str | None:
    if conf is None:
        return None
    if conf < 0.4:
        return "0.00–0.40"
    if conf < 0.6:
        return "0.40–0.60"
    if conf < 0.8:
        return "0.60–0.80"
    return "0.80–1.00"


def _write_md(path: Path, rows: list[dict[str, Any]], judge: str) -> None:
    ok = [r for r in rows if r.get("jev_ok")]
    hits1 = [r for r in ok if r.get("hit_1d") in ("hit", "miss")]
    hits5 = [r for r in ok if r.get("hit_5d") in ("hit", "miss")]
    n1 = sum(1 for r in hits1 if r["hit_1d"] == "hit")
    n5 = sum(1 for r in hits5 if r["hit_5d"] == "hit")
    lines = [
        "# Jev gold event-window study",
        "",
        f"- judge: `{judge}`",
        f"- windows: {len(rows)}（Jev 成功 {len(ok)}）",
        f"- directional 1d hit-rate（排除 neutral_call / 跳过）: "
        f"{n1}/{len(hits1)}" + (f" = {n1/len(hits1):.0%}" if hits1 else ""),
        f"- directional 5d hit-rate（排除 neutral_call / 跳过）: "
        f"{n5}/{len(hits5)}" + (f" = {n5/len(hits5):.0%}" if hits5 else ""),
        f"- 开仓次数: {sum(1 for r in ok if r.get('gate') != 'hold')}",
        "",
        "不是交易绩效。标签是随后金价；Jev 只看到事件日 state。"
        "v1 门控阈值 0.8。样本仍小，分桶只作观察。",
        "",
        "## Confidence buckets (1d directional)",
        "",
        "| bucket | n | hits |",
        "|---|---|---|",
    ]
    buckets: dict[str, list[str]] = {}
    for r in hits1:
        b = _bucket(r.get("direction_conf"))
        if b:
            buckets.setdefault(b, []).append(r["hit_1d"])
    for b in ("0.00–0.40", "0.40–0.60", "0.60–0.80", "0.80–1.00"):
        vals = buckets.get(b, [])
        h = sum(1 for v in vals if v == "hit")
        lines.append(f"| {b} | {len(vals)} | {h} |")
    lines += [
        "",
        "| date | kind | direction (conf) | risk | gate | fwd 1d | hit 1d | hit 5d | conflict share |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        conf = r.get("direction_conf")
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else ""
        lines.append(
            f"| {r['date']} | {r['kind']} | {r.get('direction')} ({conf_s}) | "
            f"{r.get('risk')} | {r.get('gate')} | {r.get('fwd_1d_pct')} | "
            f"{r.get('hit_1d')} | {r.get('hit_5d')} | {r.get('conflict_share')} |"
        )
    path.write_text("\n".join(lines) + "\n")



def main() -> int:
    parser = argparse.ArgumentParser(description="Jev gold event-window backtest")
    parser.add_argument("--out", default="reports", help="output directory")
    parser.add_argument("--resume", action="store_true", help="reuse jev_ok rows, only retry the rest")
    parser.add_argument(
        "--rerun",
        action="append",
        default=[],
        metavar="ID",
        help="force re-evaluate these event ids even with --resume (repeatable)",
    )
    args = parser.parse_args()
    _load_dotenv()
    cfg = Config.from_env()
    return run(cfg, Path(args.out), resume=args.resume, rerun=set(args.rerun))


if __name__ == "__main__":
    raise SystemExit(main())
