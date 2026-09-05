"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bugs and pass on a correct fix."""

from reporting.db import connect, seed
from reporting.report import customer_totals, render_report


def test_namesakes_are_not_merged():
    conn = connect()
    seed(
        conn,
        customers=[(1, "Sam"), (2, "Sam")],  # two different customers, same name
        orders=[(1, 1000), (2, 5000)],
    )
    totals = customer_totals(conn)
    assert len(totals) == 2, "namesake customers were merged into one row"
    assert sorted(t["total_cents"] for t in totals) == [1000, 5000]


def test_amounts_render_as_dollars():
    conn = connect()
    seed(conn, customers=[(2, "Bob")], orders=[(2, 5000)])
    assert render_report(conn) == "Bob: $50.00"


def test_full_report_both_fixes():
    conn = connect()
    seed(
        conn,
        customers=[(1, "Alice"), (2, "Bob"), (3, "Bob")],
        orders=[(1, 1000), (2, 2000), (3, 3000), (3, 250)],
    )
    text = render_report(conn)
    lines = text.splitlines()
    assert len(lines) == 3
    assert "Bob: $32.50" in lines[0]  # customer 3, highest spender first
    assert "Alice: $10.00" in lines
