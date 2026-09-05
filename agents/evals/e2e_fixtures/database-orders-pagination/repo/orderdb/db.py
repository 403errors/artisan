"""Tiny sqlite-backed order store."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer TEXT NOT NULL,
    total_cents INTEGER NOT NULL
);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA)
    return conn


def seed_orders(conn: sqlite3.Connection, orders: list[tuple[str, int]]) -> None:
    """orders: [(customer, total_cents)] — ids are assigned sequentially from 1."""
    conn.executemany("INSERT INTO orders (customer, total_cents) VALUES (?, ?)", orders)
    conn.commit()
