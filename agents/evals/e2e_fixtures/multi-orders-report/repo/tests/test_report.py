from reporting.db import connect, seed
from reporting.report import customer_totals, render_report


def _db():
    conn = connect()
    seed(conn, customers=[(1, "Alice"), (2, "Bob")], orders=[(1, 1000), (1, 500), (2, 2000)])
    return conn


def test_totals_aggregates_orders():
    totals = customer_totals(_db())
    assert len(totals) == 2
    assert totals[0]["customer"] == "Bob"  # highest spender first


def test_report_mentions_each_customer():
    text = render_report(_db())
    assert "Alice" in text
    assert "Bob" in text
