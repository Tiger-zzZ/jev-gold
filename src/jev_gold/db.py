"""SQLite 存储：快照、决策、仓位、价格。决策日志格式是校准分析的地基，改动需评审。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    judge TEXT NOT NULL,
    raw_response_json TEXT NOT NULL,
    geopolitical_risk INTEGER,
    news_direction TEXT,
    news_direction_confidence REAL,
    fed_repricing REAL,
    gated_action TEXT NOT NULL,
    gate_reason TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,        -- long | flat
    price REAL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL NOT NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_snapshot(conn: sqlite3.Connection, ts: str, state: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO snapshots (ts, state_json) VALUES (?, ?)",
        (ts, json.dumps(state, ensure_ascii=False, default=str)),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_decision(
    conn: sqlite3.Connection,
    ts: str,
    snapshot_id: int,
    judge: str,
    result_raw: dict[str, Any],
    geopolitical_risk: int | None,
    news_direction: str | None,
    news_direction_confidence: float | None,
    fed_repricing: float | None,
    gated_action: str,
    gate_reason: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO decisions
           (ts, snapshot_id, judge, raw_response_json, geopolitical_risk,
            news_direction, news_direction_confidence, fed_repricing,
            gated_action, gate_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            ts, snapshot_id, judge,
            json.dumps(result_raw, ensure_ascii=False, default=str),
            geopolitical_risk, news_direction, news_direction_confidence,
            fed_repricing, gated_action, gate_reason,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_position(
    conn: sqlite3.Connection, ts: str, action: str, price: float | None, note: str = ""
) -> None:
    conn.execute(
        "INSERT INTO positions (ts, action, price, note) VALUES (?,?,?,?)",
        (ts, action, price, note),
    )
    conn.commit()


def current_position(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT action FROM positions ORDER BY id DESC LIMIT 1").fetchone()
    return row["action"] if row else "flat"


def insert_price(conn: sqlite3.Connection, ts: str, symbol: str, price: float) -> None:
    conn.execute(
        "INSERT INTO prices (ts, symbol, price) VALUES (?,?,?)", (ts, symbol, price)
    )
    conn.commit()
