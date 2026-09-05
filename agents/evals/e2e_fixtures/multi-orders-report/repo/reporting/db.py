"""sqlite-backed store for the reporting service."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    total_cents INTEGER NOT NULL
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def seed(conn: sqlite3.Connection, customers: list[tuple[int, str]],
         orders: list[tuple[int, int]]) -> None:
    """customers: [(id, name)]; orders: [(customer_id, total_cents)]."""
    conn.executemany("INSERT INTO customers (id, name) VALUES (?, ?)", customers)
    conn.executemany("INSERT INTO orders (customer_id, total_cents) VALUES (?, ?)", orders)
    conn.commit()
