"""Customer-totals report: aggregates orders and renders a plain-text report."""

import sqlite3


def customer_totals(conn: sqlite3.Connection) -> list[dict]:
    """Total spend per customer, highest spender first."""
    rows = conn.execute(
        """
        SELECT c.name, SUM(o.total_cents) AS total
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        GROUP BY c.name
        ORDER BY total DESC
        """
    ).fetchall()
    return [{"customer": name, "total_cents": total} for name, total in rows]


def render_report(conn: sqlite3.Connection) -> str:
    """Renders customer totals as 'Name: $X.XX' lines."""
    lines = []
    for row in customer_totals(conn):
        lines.append(f"{row['customer']}: ${row['total_cents']:.2f}")
    return "\n".join(lines)
