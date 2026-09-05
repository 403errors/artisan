"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

from orderdb.db import connect, seed_orders
from orderdb.orders import list_orders

SEED = [(f"customer-{i}", 100 * i) for i in range(1, 10)]  # ids 1..9


def _db():
    conn = connect()
    seed_orders(conn, SEED)
    return conn


def _ids(rows):
    return [r["id"] for r in rows]


def test_page_one_starts_at_the_first_row():
    assert _ids(list_orders(_db(), page=1, per_page=3)) == [1, 2, 3]


def test_pages_are_contiguous_and_non_overlapping():
    conn = _db()
    page1 = _ids(list_orders(conn, page=1, per_page=4))
    page2 = _ids(list_orders(conn, page=2, per_page=4))
    assert page1 == [1, 2, 3, 4]
    assert page2 == [5, 6, 7, 8]


def test_full_scan_covers_every_row_exactly_once():
    conn = _db()
    seen = _ids(list_orders(conn, page=1, per_page=5)) + _ids(list_orders(conn, page=2, per_page=5))
    assert sorted(seen) == list(range(1, 10))
