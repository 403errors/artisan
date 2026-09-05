"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

from shop.invoice import build_invoice
from shop.pricing import apply_member_discount, line_total


def test_member_discount_applied_exactly_once():
    assert apply_member_discount(1000, is_member=True) == 900


def test_member_discount_rounding_edge():
    # 999 * 0.9 = 899.1 -> 899 with integer floor division, applied exactly once.
    assert apply_member_discount(999, is_member=True) == 899


def test_member_invoice_total():
    invoice = build_invoice(
        [{"name": "gadget", "unit_price_cents": 2000, "quantity": 3}], is_member=True
    )
    assert invoice["total_cents"] == 5400


def test_non_member_unaffected():
    assert apply_member_discount(1234, is_member=False) == 1234
    assert line_total(1234, 2, is_member=False) == 2468
