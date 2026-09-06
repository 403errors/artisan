"""Order/refund request handlers."""


def create_order(items: list[dict]) -> dict:
    """Creates an order: each item is {"sku": str, "quantity": int, "unit_price": float}."""
    total = sum(i["quantity"] * i["unit_price"] for i in items)
    return {"status": 201, "body": {"total": round(total, 2), "n_items": len(items)}}


def create_refund(items: list[dict]) -> dict:
    """Creates a refund against returned items — same item shape as create_order."""
    total = sum(i["quantity"] * i["unit_price"] for i in items)
    return {"status": 201, "body": {"refund_total": round(total, 2), "n_items": len(items)}}
