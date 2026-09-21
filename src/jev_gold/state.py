"""state 组装器：把四路数据揉成 Jev 的唯一输入。

原则：Jev 无世界知识，判断所需的一切都必须在这里面。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

# FOMC 政策声明日（两日会议的第二天，14:00 ET）。
# 2022–2023：federalreserve.gov 历史日历；2024–2026：官方日程公告。
FOMC_STATEMENT_DATES = [
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15),
    date(2022, 7, 27), date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
]


def _days_to_next_fomc(today: date) -> int | None:
    future = [d for d in FOMC_STATEMENT_DATES if d >= today]
    return (min(future) - today).days if future else None


def build_state(
    pulse: dict[str, Any],
    headlines: list[dict[str, str]],
    macro: dict[str, Any],
    price: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "asset": "gold (COMEX GC=F front month, USD)",
        "conflict_news_pulse": pulse,
        "gold_headlines_3h": headlines,
        "macro": {**macro, "days_to_next_fomc": _days_to_next_fomc(now.date())},
        "price": price,
    }
