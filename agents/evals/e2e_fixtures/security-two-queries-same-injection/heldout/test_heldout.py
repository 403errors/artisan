"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

import sqlite3

import pytest

from reportdb import queries


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE users (id INTEGER, name TEXT, email TEXT)")
    c.execute("CREATE TABLE orders (id INTEGER, ref TEXT, total REAL)")
    c.execute("INSERT INTO users VALUES (1, 'ada', 'ada@example.com')")
    c.execute("INSERT INTO users VALUES (2, 'grace', 'grace@example.com')")
    c.execute("INSERT INTO orders VALUES (1, 'A-100', 99.5)")
    c.execute("INSERT INTO orders VALUES (2, 'B-200', 10.0)")
    yield c
    c.close()


@pytest.mark.parametrize("payload", ["' OR '1'='1", "x' OR '1'='1' --"])
def test_user_lookup_resists_injection(conn, payload):
    assert queries.find_users_by_name(conn, payload) == []
    # Table still intact afterwards.
    assert len(conn.execute("SELECT * FROM users").fetchall()) == 2


@pytest.mark.parametrize("payload", ["' OR '1'='1", "x' OR '1'='1' --"])
def test_order_lookup_resists_injection(conn, payload):
    # The sibling query has the same defect class and must be fixed too.
    assert queries.find_orders_by_ref(conn, payload) == []


def test_exact_matches_still_work(conn):
    assert queries.find_users_by_name(conn, "grace") == [(2, "grace", "grace@example.com")]
    assert queries.find_orders_by_ref(conn, "B-200") == [(2, "B-200", 10.0)]
