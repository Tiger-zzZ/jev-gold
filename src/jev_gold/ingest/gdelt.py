"""GDELT 客户端：文件源为主（冲突脉搏），DOC API 为辅（头条）。

已验证事实（2026-09-20 实测）：
- DOC API（api.gdeltproject.org）限流极严：名义 5s/次，实测冷却 ~2h 级 → 只做非关键数据
- 文件源（data.gdeltproject.org）独立且通畅：lastupdate.txt 每 15min 给出三个 zip 的 URL
- Events zip（~40KB）：15min 全球事件，含 GoldsteinScale/AvgTone/CAMEO 编码
- 同一文件格式历史回溯到 2015 → Phase 3 回测复用本解析器
- artlist 实测结构：{"articles":[{url,title,seendate,domain,language,sourcecountry}]}
"""
from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

LASTUPDATE = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = {"User-Agent": "jev-gold/0.1 (research PoC; contact: local)"}

# CAMEO 冲突类根编码：13 威胁 / 14 抗议 / 15 展示武力 / 16 降低关系 / 17 胁迫 / 18 攻击 / 19 战斗 / 20 大规模暴力
CONFLICT_ROOT_CODES = {str(i) for i in range(13, 21)}

# GDELT 2.0 Events TSV 列索引（无表头；标准 58+ 列布局）
COL_EVENT_ROOT = 28   # EventRootCode
COL_QUAD_CLASS = 29   # QuadClass: 1口头合作 2物质合作 3口头冲突 4物质冲突
COL_GOLDSTEIN = 30    # GoldsteinScale: -10(最对抗) ~ +10(最合作)
COL_NUM_MENTIONS = 31
COL_AVG_TONE = 34     # 该事件报道的平均语气

MIN_INTERVAL_S = 6.0
CACHE_DIR = Path(".cache/gdelt")
_last_call_ts = 0.0


def _throttle() -> None:
    global _last_call_ts
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call_ts)
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.monotonic()


# ---------- 主路径：Events 文件源 ----------

def _latest_export_url() -> str | None:
    resp = requests.get(LASTUPDATE, headers=UA, timeout=20)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
            return parts[2].replace("http://", "https://")
    return None


def _step_back(url: str, minutes: int = 15) -> str | None:
    """lastupdate.txt 会提前引用尚未生成的文件（实测 03:55 列出 040000 但 404），
    按 15 分钟步长回退构造候选 URL。"""
    m = re.search(r"/(\d{14})\.export\.CSV\.zip$", url)
    if not m:
        return None
    ts = datetime.strptime(m.group(1), "%Y%m%d%H%M%S") - timedelta(minutes=minutes)
    return url[: m.start()] + "/" + ts.strftime("%Y%m%d%H%M%S") + ".export.CSV.zip"


def _fetch_export_zip() -> tuple[str, bytes]:
    url = _latest_export_url()
    if not url:
        raise RuntimeError("lastupdate.txt 中未找到 export zip")
    candidates = [url] + [u for s in (1, 2) if (u := _step_back(url, 15 * s))]
    last_exc: Exception | None = None
    for candidate in candidates:
        try:
            resp = requests.get(candidate, headers=UA, timeout=60)
            resp.raise_for_status()
            return candidate, resp.content
        except requests.HTTPError as exc:
            last_exc = exc
            if exc.response is not None and exc.response.status_code != 404:
                raise
    raise RuntimeError(f"export zip 连续 404：{candidates}") from last_exc


def _f(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pulse_from_zip_bytes(content: bytes, source_label: str) -> dict[str, Any]:
    """从 Events zip（15min 或日频，列布局兼容）聚合冲突脉搏。"""
    total = conflict = fight = mass_violence = 0
    goldstein_sum = tone_sum = 0.0
    goldstein_n = tone_n = 0
    conflict_mentions = 0

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            for row in csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t"):
                if len(row) <= COL_AVG_TONE:
                    continue
                total += 1
                tone = _f(row[COL_AVG_TONE])
                if tone is not None:
                    tone_sum += tone
                    tone_n += 1
                root = row[COL_EVENT_ROOT]
                if root in CONFLICT_ROOT_CODES:
                    conflict += 1
                    g = _f(row[COL_GOLDSTEIN])
                    if g is not None:
                        goldstein_sum += g
                        goldstein_n += 1
                    conflict_mentions += int(_f(row[COL_NUM_MENTIONS]) or 0)
                    if root == "19":
                        fight += 1
                    elif root == "20":
                        mass_violence += 1

    if total == 0:
        raise RuntimeError("export 文件解析出 0 条事件")
    return {
        "source": source_label,
        "events_total": total,
        "events_total_15min": total,  # 实时路径兼容字段
        "conflict_events": conflict,
        "conflict_share": round(conflict / total, 4),
        "goldstein_mean_conflict": round(goldstein_sum / goldstein_n, 3) if goldstein_n else None,
        "avgtone_mean_all": round(tone_sum / tone_n, 3) if tone_n else None,
        "conflict_mentions": conflict_mentions,
        "fight_events": fight,
        "mass_violence_events": mass_violence,
    }


def conflict_pulse() -> dict[str, Any]:
    """从最新 15 分钟 Events 文件聚合冲突脉搏。"""
    url, content = _fetch_export_zip()
    pulse = pulse_from_zip_bytes(content, "gdelt_events_file_15min")
    pulse["file"] = url.rsplit("/", 1)[-1]
    return pulse


def _get_bytes(url: str, timeout: int = 120) -> bytes:
    """大文件下载：https 失败则回退 http，并重试。"""
    last_exc: Exception | None = None
    candidates = [url]
    if url.startswith("https://"):
        candidates.append("http://" + url[len("https://"):])
    for candidate in candidates:
        for attempt in range(3):
            try:
                resp = requests.get(candidate, headers=UA, timeout=timeout, stream=True)
                resp.raise_for_status()
                chunks: list[bytes] = []
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        chunks.append(chunk)
                data = b"".join(chunks)
                if len(data) < 1000:
                    raise RuntimeError(f"download too small ({len(data)} bytes): {candidate}")
                return data
            except Exception as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}") from last_exc


def conflict_pulse_for_date(day: datetime) -> dict[str, Any]:
    """日频历史文件：https://data.gdeltproject.org/events/YYYYMMDD.export.CSV.zip"""
    stamp = day.strftime("%Y%m%d")
    fname = f"{stamp}.export.CSV.zip"
    cache_path = CACHE_DIR / fname
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        content = cache_path.read_bytes()
    else:
        url = f"https://data.gdeltproject.org/events/{fname}"
        content = _get_bytes(url)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
    pulse = pulse_from_zip_bytes(content, "gdelt_events_daily")
    pulse["file"] = fname
    return pulse


# ---------- 辅路径：DOC API 头条（限流敏感，失败仅降级不熔断） ----------

GOLD_QUERY = '(gold OR "gold price") sourcelang:english'


def gold_headlines(n: int = 5, timespan: str = "3h") -> list[dict[str, str]]:
    """非关键路径：429 立即失败，由 loop 降级为空列表，不阻塞 15min 节拍。"""
    params: dict[str, Any] = {
        "query": GOLD_QUERY, "mode": "artlist", "format": "json",
        "timespan": timespan, "maxrecords": n,
    }
    _throttle()
    resp = requests.get(GDELT_DOC, params=params, headers=UA, timeout=15)
    resp.raise_for_status()
    articles = (resp.json() or {}).get("articles") or []
    return [
        {"title": a.get("title", "").strip(), "domain": a.get("domain", ""), "seendate": a.get("seendate", "")}
        for a in articles[:n]
    ]
