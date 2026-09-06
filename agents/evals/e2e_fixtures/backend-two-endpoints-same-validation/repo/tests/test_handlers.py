import pytest

from shopapi import handlers

MOUSE = {"sku": "mouse", "quantity": 2, "unit_price": 25.0}


def test_create_order_computes_total():
    resp = handlers.create_order([MOUSE])
    assert resp["status"] == 201
    assert resp["body"]["total"] == 50.0


def test_create_refund_computes_total():
    resp = handlers.create_refund([MOUSE])
    assert resp["body"]["refund_total"] == 50.0


def test_create_order_rejects_negative_quantity():
    # Repro for the reported issue: quantity must be a positive integer.
    with pytest.raises(ValueError):
        handlers.create_order([{"sku": "mouse", "quantity": -1, "unit_price": 25.0}])
