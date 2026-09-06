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
    yield c
    c.close()


def test_find_users_by_exact_name(conn):
    assert queries.find_users_by_name(conn, "ada") == [(1, "ada", "ada@example.com")]


def test_find_orders_by_ref(conn):
    assert queries.find_orders_by_ref(conn, "A-100") == [(1, "A-100", 99.5)]


def test_name_lookup_treats_quotes_literally(conn):
    # Repro for the reported issue: a name containing a quote must not break out of the SQL.
    assert queries.find_users_by_name(conn, "' OR '1'='1") == []
