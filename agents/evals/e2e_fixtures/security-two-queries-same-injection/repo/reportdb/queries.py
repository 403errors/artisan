"""Reporting queries over the orders SQLite database."""


def find_users_by_name(conn, name: str) -> list[tuple]:
    """Looks up users by exact name."""
    return conn.execute(f"SELECT id, name, email FROM users WHERE name = '{name}'").fetchall()


def find_orders_by_ref(conn, ref: str) -> list[tuple]:
    """Looks up orders by their reference code."""
    return conn.execute(f"SELECT id, ref, total FROM orders WHERE ref = '{ref}'").fetchall()
