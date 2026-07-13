from __future__ import annotations

import json
import sqlite3


class CityCache:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS cities (
                id TEXT PRIMARY KEY,
                payload BLOB NOT NULL,
                buildings TEXT NOT NULL,
                region_cells INTEGER,
                road_estimate INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS layouts (
                id TEXT PRIMARY KEY,
                city_id TEXT NOT NULL,
                k INTEGER,
                achieved INTEGER,
                layout TEXT NOT NULL,
                roads_count INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self._conn.commit()

    def store_city(self, city_id: str, payload: bytes,
                   buildings: list[dict], region_cells: int,
                   road_estimate: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cities (id, payload, buildings, region_cells, road_estimate) "
            "VALUES (?, ?, ?, ?, ?)",
            (city_id, payload, json.dumps(buildings), region_cells, road_estimate)
        )
        self._conn.commit()

    def get_city(self, city_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM cities WHERE id = ?", (city_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "payload": json.loads(row["payload"]),
            "buildings": json.loads(row["buildings"]),
            "region_cells": row["region_cells"],
            "road_estimate": row["road_estimate"],
            "created_at": row["created_at"],
        }

    def list_cities(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, region_cells, road_estimate, created_at FROM cities ORDER BY created_at DESC"
        ).fetchall()
        return [{"id": r["id"], "region_cells": r["region_cells"],
                 "road_estimate": r["road_estimate"], "created_at": r["created_at"]}
                for r in rows]

    def store_layout(self, layout_id: str, city_id: str, k: int,
                     achieved: int, layout: dict, roads_count: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO layouts (id, city_id, k, achieved, layout, roads_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (layout_id, city_id, k, achieved, json.dumps(layout), roads_count)
        )
        self._conn.commit()

    def get_layout(self, layout_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM layouts WHERE id = ?", (layout_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"], "city_id": row["city_id"],
            "k": row["k"], "achieved": row["achieved"],
            "layout": json.loads(row["layout"]),
            "roads_count": row["roads_count"],
            "created_at": row["created_at"],
        }

    def list_layouts(self, city_id: str | None = None) -> list[dict]:
        if city_id is not None:
            rows = self._conn.execute(
                "SELECT id, city_id, k, achieved, roads_count, created_at "
                "FROM layouts WHERE city_id = ? ORDER BY created_at DESC",
                (city_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, city_id, k, achieved, roads_count, created_at "
                "FROM layouts ORDER BY created_at DESC"
            ).fetchall()
        return [{"id": r["id"], "city_id": r["city_id"], "k": r["k"],
                 "achieved": r["achieved"], "roads_count": r["roads_count"],
                 "created_at": r["created_at"]}
                for r in rows]

    def delete_layout(self, layout_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM layouts WHERE id = ?", (layout_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
