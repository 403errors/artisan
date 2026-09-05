from shop.invoice import build_invoice


def test_invoice_sums_lines_for_non_member():
    invoice = build_invoice(
        [{"name": "widget", "unit_price_cents": 250, "quantity": 4}], is_member=False
    )
    assert invoice["total_cents"] == 1000
    assert invoice["lines"] == [{"name": "widget", "amount_cents": 1000}]
