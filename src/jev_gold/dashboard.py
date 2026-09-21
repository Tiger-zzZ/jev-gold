"""单文件 HTML 仪表盘：实时决策日志 + 事件窗口回测。无额外依赖。"""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
from pathlib import Path

from .config import Config
from .loop import _load_dotenv


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(conn.execute(sql, args))


def _svg_line(points: list[tuple[float, float]], w: int = 640, h: int = 160) -> str:
    if len(points) < 2:
        return f'<svg viewBox="0 0 {w} {h}" class="chart"><text x="12" y="24">no data</text></svg>'
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    dx = (maxx - minx) or 1.0
    dy = (maxy - miny) or 1.0
    pad = 8
    def sx(x: float) -> float:
        return pad + (x - minx) / dx * (w - 2 * pad)
    def sy(y: float) -> float:
        return h - pad - (y - miny) / dy * (h - 2 * pad)
    d = " ".join(
        f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(points)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" class="chart">'
        f'<path d="{d}" fill="none" stroke="#c9a227" stroke-width="2"/>'
        f'<text x="{pad}" y="14" fill="#888" font-size="11">{miny:.1f}–{maxy:.1f}</text>'
        f"</svg>"
    )


def _paper_pnl(decisions: list[sqlite3.Row], prices: dict[str, float]) -> list[tuple[str, float, float]]:
    """按决策时间走 long/flat，对比始终 long。价格缺失则跳过该点。"""
    pos = "flat"
    cash = 1.0
    hold = 1.0
    last_px: float | None = None
    out: list[tuple[str, float, float]] = []
    for d in decisions:
        px = prices.get(d["ts"])
        if px is None or px <= 0:
            continue
        if last_px is not None:
            ret = px / last_px
            hold *= ret
            if pos == "long":
                cash *= ret
        action = d["gated_action"]
        if action in ("long", "flat"):
            pos = action
        last_px = px
        out.append((d["ts"], cash, hold))
    return out


def render(cfg: Config, out_path: Path, study_path: Path) -> None:
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    decisions = _rows(conn, "SELECT * FROM decisions ORDER BY id ASC")
    prices_rows = _rows(conn, "SELECT ts, price FROM prices ORDER BY id ASC")
    latest = decisions[-1] if decisions else None
    price_map = {r["ts"]: float(r["price"]) for r in prices_rows}

    study = []
    if study_path.exists():
        study = json.loads(study_path.read_text())

    price_pts = [(i, float(r["price"])) for i, r in enumerate(prices_rows)]
    conf_pts = [
        (i, float(d["news_direction_confidence"]))
        for i, d in enumerate(decisions)
        if d["news_direction_confidence"] is not None
    ]
    pnl = _paper_pnl(decisions, price_map)
    pnl_pts = [(i, v[1]) for i, v in enumerate(pnl)]
    bh_pts = [(i, v[2]) for i, v in enumerate(pnl)]

    def td(v: object) -> str:
        return html.escape("" if v is None else str(v))

    live_rows = "".join(
        "<tr>"
        f"<td>{td(d['ts'])}</td><td>{td(d['judge'])}</td>"
        f"<td>{td(d['news_direction'])}</td><td>{td(d['news_direction_confidence'])}</td>"
        f"<td>{td(d['geopolitical_risk'])}</td><td>{td(d['fed_repricing'])}</td>"
        f"<td>{td(d['gated_action'])}</td>"
        "</tr>"
        for d in reversed(decisions[-24:])
    )
    study_rows = "".join(
        "<tr>"
        f"<td>{td(r.get('date'))}</td><td>{td(r.get('kind'))}</td>"
        f"<td>{td(r.get('direction'))}</td><td>{td(r.get('direction_conf'))}</td>"
        f"<td>{td(r.get('risk'))}</td><td>{td(r.get('gate'))}</td>"
        f"<td>{td(r.get('fwd_1d_pct'))}</td><td>{td(r.get('hit_1d'))}</td>"
        f"<td>{td(r.get('hit_5d'))}</td>"
        "</tr>"
        for r in study
    )
    latest_block = "<p>暂无实时决策。先跑 <code>python -m jev_gold.loop --once</code>。</p>"
    if latest:
        latest_block = (
            f"<dl class='kpis'>"
            f"<div><dt>time</dt><dd>{td(latest['ts'])}</dd></div>"
            f"<div><dt>direction</dt><dd>{td(latest['news_direction'])} "
            f"({td(latest['news_direction_confidence'])})</dd></div>"
            f"<div><dt>risk</dt><dd>{td(latest['geopolitical_risk'])}</dd></div>"
            f"<div><dt>fed_repricing</dt><dd>{td(latest['fed_repricing'])}</dd></div>"
            f"<div><dt>gate</dt><dd>{td(latest['gated_action'])}</dd></div>"
            f"</dl><p class='reason'>{td(latest['gate_reason'])}</p>"
        )

    page = f"""<!doctype html>
<html lang="zh">
<meta charset="utf-8"/>
<title>jev-gold dashboard</title>
<style>
body {{ font: 14px/1.45 ui-sans-serif, system-ui; margin: 24px; color: #1a1a1a; background: #faf8f4; }}
h1,h2 {{ font-weight: 600; }}
.kpis {{ display: flex; gap: 16px; flex-wrap: wrap; }}
.kpis div {{ background: #fff; padding: 10px 14px; border: 1px solid #e6e0d4; min-width: 140px; }}
dt {{ color: #777; font-size: 11px; text-transform: uppercase; }}
dd {{ margin: 0; font-size: 18px; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; }}
th,td {{ border: 1px solid #e6e0d4; padding: 6px 8px; text-align: left; }}
.chart {{ width: 100%; height: 160px; background: #fff; border: 1px solid #e6e0d4; }}
.note {{ color: #666; max-width: 72ch; }}
.reason {{ color: #444; }}
</style>
<h1>Jev Gold Sentinel</h1>
<p class="note">纸面研究仪表盘。Jev 只做判断；代码做门控。不构成投资建议。</p>
<h2>Latest live decision</h2>
{latest_block}
<h2>Gold prints (live loop)</h2>
{_svg_line(price_pts)}
<h2>Direction confidence (live)</h2>
{_svg_line(conf_pts)}
<h2>Paper NAV vs buy&amp;hold</h2>
<p class="note">黄线策略（long/flat），灰线始终多头。v1 阈值下几乎全是 hold，两条线会重合或策略近似现金。</p>
{_svg_line(pnl_pts)}
{_svg_line(bh_pts)}
<h2>Recent live decisions</h2>
<table><thead><tr><th>ts</th><th>judge</th><th>direction</th><th>conf</th><th>risk</th><th>fed</th><th>gate</th></tr></thead>
<tbody>{live_rows or '<tr><td colspan="7">empty</td></tr>'}</tbody></table>
<h2>Event-window study</h2>
<table><thead><tr><th>date</th><th>kind</th><th>direction</th><th>conf</th><th>risk</th><th>gate</th><th>fwd1d</th><th>hit1d</th><th>hit5d</th></tr></thead>
<tbody>{study_rows or '<tr><td colspan="9">run python -m jev_gold.backtest</td></tr>'}</tbody></table>
</html>
"""
    out_path.write_text(page)
    print(f"wrote {out_path}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write jev-gold HTML dashboard")
    parser.add_argument("--out", default="reports/dashboard.html")
    parser.add_argument("--study", default="reports/event_study.json")
    args = parser.parse_args()
    _load_dotenv()
    cfg = Config.from_env()
    render(cfg, Path(args.out), Path(args.study))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
