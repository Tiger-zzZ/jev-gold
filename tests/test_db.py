"""SQLite 四表 roundtrip。"""
from __future__ import annotations

import unittest

from jev_gold import db


class DbTests(unittest.TestCase):
    def test_snapshot_decision_position_price(self):
        conn = db.connect(":memory:")
        sid = db.insert_snapshot(conn, "2022-02-24T18:00:00+00:00", {"k": 1})
        did = db.insert_decision(
            conn,
            "2022-02-24T18:00:00+00:00",
            sid,
            "mock",
            {"answers": {}},
            3,
            "bullish_gold",
            0.65,
            0.39,
            "hold",
            "low conf",
        )
        self.assertGreater(sid, 0)
        self.assertGreater(did, 0)
        self.assertEqual(db.current_position(conn), "flat")
        db.insert_position(conn, "2022-02-24T18:00:00+00:00", "long", 177.14, "test")
        self.assertEqual(db.current_position(conn), "long")
        db.insert_price(conn, "2022-02-24T18:00:00+00:00", "GLD", 177.14)
        n = conn.execute("SELECT COUNT(*) AS n FROM prices").fetchone()["n"]
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
