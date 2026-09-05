"""Paginated order queries. Pages are 1-indexed: page 1 is the first page."""

import sqlite3


def list_orders(conn: sqlite3.Connection, page: int, per_page: int) -> list[dict]:
    """Returns one page of orders, oldest (lowest id) first."""
    offset = page * per_page
    rows = conn.execute(
        "SELECT id, customer, total_cents FROM orders ORDER BY id LIMIT ? OFFSET ?",
        (per_page, offset),
    ).fetchall()
    return [
        {"id": row[0], "customer": row[1], "total_cents": row[2]} for row in rows
    ]
