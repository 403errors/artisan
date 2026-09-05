from orderdb.db import connect, seed_orders
from orderdb.orders import list_orders

SEED = [(f"customer-{i}", 100 * i) for i in range(1, 10)]  # ids 1..9


def _db():
    conn = connect()
    seed_orders(conn, SEED)
    return conn


def test_page_returns_at_most_per_page_rows():
    conn = _db()
    assert len(list_orders(conn, page=1, per_page=3)) == 3
    assert len(list_orders(conn, page=2, per_page=3)) == 3


def test_page_beyond_data_is_empty():
    conn = _db()
    assert list_orders(conn, page=5, per_page=3) == []


def test_rows_have_expected_shape():
    conn = _db()
    row = list_orders(conn, page=1, per_page=1)[0]
    assert set(row) == {"id", "customer", "total_cents"}
