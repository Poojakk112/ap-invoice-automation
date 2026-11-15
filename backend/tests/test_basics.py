from decimal import Decimal

from apflow import ids
from apflow.config import allocate, load_policy
from apflow.money import line_tax, q2


def test_id_formats_are_zero_padded():
    assert ids.vendor_id(1) == "VND-00001"
    assert ids.po_id(1, 2026) == "PO-2026-000001"
    assert ids.grn_id(42, 2026) == "GRN-2026-000042"
    inv = ids.invoice_id("APE01", 7, 2026)
    assert inv == "INV-APE01-2026-000007"
    assert ids.invoice_line_id(inv, 1) == "INVL-INV-APE01-2026-000007-01"
    assert ids.is_valid("invoice_line_id", ids.invoice_line_id(inv, 3))
    assert not ids.is_valid("vendor_id", "VND-1")


def test_rounding_is_half_up_to_cents():
    assert q2("2.345") == Decimal("2.35")
    assert q2("2.344") == Decimal("2.34")
    assert line_tax("100.00", "0.0825") == Decimal("8.25")


def test_allocate_is_exact_and_deterministic():
    mix = {"clean": .70, "price": .10, "qty": .08, "dup": .05, "rcpt": .04, "tax": .03}
    out = allocate(2000, mix)
    assert out == {"clean": 1400, "price": 200, "qty": 160, "dup": 100, "rcpt": 80, "tax": 60}
    assert sum(allocate(203, mix).values()) == 203
    assert allocate(203, mix) == allocate(203, mix)


def test_approval_matrix_tiers():
    p = load_policy()
    assert p.approval_roles(Decimal("10000.00")) == ["SYSTEM_AUTO"]
    assert p.approval_roles(Decimal("10000.01")) == ["DEPT_MANAGER"]
    assert p.approval_roles(Decimal("100000.01")) == ["DEPT_MANAGER", "FINANCE_CONTROLLER"]
    # non-PO invoices always need a human approver
    assert p.approval_roles(Decimal("50.00"), non_po=True) == ["DEPT_MANAGER"]


def test_scale_keeps_ratios():
    p = load_policy(scale=0.1)
    assert p.volumes["invoices"] == 200
    assert p.volumes["purchase_order_lines"] >= p.volumes["purchase_orders"]
