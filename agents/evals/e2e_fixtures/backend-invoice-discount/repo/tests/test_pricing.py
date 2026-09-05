from shop.pricing import apply_member_discount, line_total


def test_non_member_pays_full_price():
    assert apply_member_discount(1000, is_member=False) == 1000


def test_member_gets_ten_percent_off_once():
    # Repro for the reported issue: members currently see the discount applied twice
    # (810 instead of 900 on a 1000-cent item).
    assert apply_member_discount(1000, is_member=True) == 900


def test_line_total_uses_discounted_unit_price():
    assert line_total(500, 2, is_member=True) == 900
