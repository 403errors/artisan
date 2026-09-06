"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

import pytest

from shopapi import handlers

MOUSE = {"sku": "mouse", "quantity": 2, "unit_price": 25.0}


@pytest.mark.parametrize("quantity", [-1, 0, 1.5, "two"])
def test_create_order_rejects_bad_quantities(quantity):
    with pytest.raises(ValueError):
        handlers.create_order([{"sku": "mouse", "quantity": quantity, "unit_price": 25.0}])


@pytest.mark.parametrize("quantity", [-1, 0, 1.5, "two"])
def test_create_refund_rejects_bad_quantities(quantity):
    # The sibling endpoint has the same defect class and must be fixed too.
    with pytest.raises(ValueError):
        handlers.create_refund([{"sku": "mouse", "quantity": quantity, "unit_price": 25.0}])


def test_valid_paths_still_work():
    assert handlers.create_order([MOUSE])["body"]["total"] == 50.0
    assert handlers.create_refund([MOUSE])["body"]["refund_total"] == 50.0
