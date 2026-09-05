"""Invoice building on top of pricing."""

from shop.pricing import line_total


def build_invoice(items: list[dict], is_member: bool) -> dict:
    """items: [{"name": str, "unit_price_cents": int, "quantity": int}]"""
    lines = []
    total = 0
    for item in items:
        amount = line_total(item["unit_price_cents"], item["quantity"], is_member)
        lines.append({"name": item["name"], "amount_cents": amount})
        total += amount
    return {"lines": lines, "total_cents": total}
