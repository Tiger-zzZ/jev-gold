"""决策循环：取数 → 组装 state → Jev 判断 → 门控 → 落库。

熔断原则：GDELT 完全失败 → 本拍不动仓（hold），只记快照，照常进入下一拍。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import Config
from .gate import HOLD, decide
from .ingest import fred, gdelt, price
from .judge import make_judge
from .state import build_state

LOOP_INTERVAL_S = 15 * 60


def _load_dotenv(path: Path = Path(".env")) -> None:
    """极简 .env 加载，避免引入 python-dotenv 依赖。"""
    if not path.exists():
        return
    import os

    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            k, v = key.strip(), value.strip()
            if k and (k not in os.environ or not os.environ[k]):
                os.environ[k] = v


def run_once(cfg: Config) -> int:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect(cfg.db_path)

    # 1) 取数：每路独立降级。冲突脉搏（文件源）是关键数据，失败即熔断本拍；
    #    头条（DOC API，限流敏感）失败仅降级。
    try:
        pulse = gdelt.conflict_pulse()
        data_ok = True
    except Exception as exc:
        print(f"[circuit-breaker] GDELT 文件源失败：{exc}", file=sys.stderr)
        pulse, data_ok = {}, False

    try:
        headlines = gdelt.gold_headlines()
    except Exception as exc:
        print(f"[degrade] GDELT 头条失败（忽略）：{exc}", file=sys.stderr)
        headlines = []

    macro = fred.macro_snapshot(cfg.fred_api_key)
    gold = price.gold_snapshot()

    if gold.get("last") is not None:
        db.insert_price(conn, ts, str(gold["symbol"]), float(gold["last"]))

    # 2) 组装 + 3) 判断 + 4) 门控
    state = build_state(pulse, headlines, macro, gold)
    snapshot_id = db.insert_snapshot(conn, ts, state)

    judge = make_judge(
        cfg.judge_backend,
        api_key=cfg.jev_api_key,
        base_url=cfg.jev_base_url,
        model=cfg.jev_model,
    ) if cfg.judge_backend == "jev" else make_judge("mock")

    result = judge.evaluate(state)
    action, reason = decide(result)
    if not data_ok:
        action, reason = HOLD, "数据缺失（GDELT 失败），本拍不动仓"

    db.insert_decision(
        conn, ts, snapshot_id, judge.name, result.raw,
        result.geopolitical_risk, result.news_direction,
        result.news_direction_confidence, result.fed_repricing,
        action, reason,
    )

    # 5) 仓位变更才写 positions
    if action != HOLD and action != db.current_position(conn):
        db.insert_position(conn, ts, action, gold.get("last"), reason)

    # 摘要
    print(f"[{ts}] judge={judge.name} data_ok={data_ok}", flush=True)
    print(f"  price: {gold.get('symbol')} {gold.get('last')}  24h={gold.get('change_24h_pct')}%", flush=True)
    print(f"  pulse: events={pulse.get('events_total_15min')} conflict_share={pulse.get('conflict_share')}"
          f" goldstein={pulse.get('goldstein_mean_conflict')} tone={pulse.get('avgtone_mean_all')}", flush=True)
    print(f"  jev: risk={result.geopolitical_risk} direction={result.news_direction}"
          f"(conf={result.news_direction_confidence}) fed_repricing={result.fed_repricing}", flush=True)
    print(f"  gate: {action} — {reason}", flush=True)
    print(
        f"  macro: real_yield={macro.get('real_yield_10y')} dollar={macro.get('dollar_index')}"
        f" fomc_in={state['macro'].get('days_to_next_fomc')}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="jev-gold 决策循环")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="单跑一次")
    group.add_argument("--forever", action="store_true", help="15 分钟常驻循环")
    args = parser.parse_args()

    _load_dotenv()
    cfg = Config.from_env()

    if args.once:
        return run_once(cfg)

    while True:
        try:
            run_once(cfg)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # 循环级兜底，绝不中断常驻进程
            print(f"[loop] 未捕获异常（继续运行）：{exc}", file=sys.stderr, flush=True)
        time.sleep(LOOP_INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
