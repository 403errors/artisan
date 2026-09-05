"""Pricing logic for the shop. All prices are integer cents."""

MEMBER_DISCOUNT_PCT = 10


def apply_member_discount(price_cents: int, is_member: bool) -> int:
    """Returns the price with the member discount applied when is_member is True."""
    if not is_member:
        return price_cents
    discounted = price_cents * (100 - MEMBER_DISCOUNT_PCT) // 100
    return discounted * (100 - MEMBER_DISCOUNT_PCT) // 100


def line_total(unit_price_cents: int, quantity: int, is_member: bool) -> int:
    """Total for one invoice line: discounted unit price times quantity."""
    return apply_member_discount(unit_price_cents, is_member) * quantity
