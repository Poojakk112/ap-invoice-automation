"""Rule-level tests on a tiny hand-built world: one vendor, one PO, one receipt."""

from datetime import date
from decimal import Decimal

import pytest

from apflow.config import load_policy
from apflow.generator.documents import render
from apflow.pipeline.engine import Context, Decision, DecisionEngine, PaymentSafetyError

POLICY = load_policy()
VENDOR = {"vendor_id": "VND-00001", "vendor_code": "APE01", "vendor_name": "Apex Tech Works LLC",
          "tax_id": "08-1234567", "status": "ACTIVE", "closed_date": "", "payment_terms_days": "30",
          "payment_method": "ACH"}


def world(received=10, vendor=None):
    v = dict(VENDOR, **(vendor or {}))
    tables = {
        "vendors": [v],
        "purchase_orders": [{"po_id": "PO-2026-000001", "vendor_id": "VND-00001", "po_date": "2026-03-01"}],
        "purchase_order_lines": [{"po_line_id": "PO-2026-000001-01", "po_id": "PO-2026-000001",
                                  "sku": "SKU-ITH-0001", "unit_price": "100.00", "quantity_ordered": "10",
                                  "tax_code": "TX8"}],
        "goods_receipts": [{"grn_id": "GRN-2026-000001", "receipt_date": "2026-03-10"}] if received else [],
        "goods_receipt_lines": [{"grn_line_id": "GRN-2026-000001-01", "grn_id": "GRN-2026-000001",
                                 "po_line_id": "PO-2026-000001-01", "quantity_received": str(received)}]
        if received else [],
    }
    return DecisionEngine(Context(tables, POLICY), POLICY)


def doc(qty=10, price="100.00", tax_code="TX8", number="APE01-26-0001", inv_date=date(2026, 3, 12),
        total_delta="0", tax_override=None, n=1, po="PO-2026-000001"):
    price = Decimal(price)
    amount = (qty * price).quantize(Decimal("0.01"))
    rate = POLICY.tax_rates[tax_code]
    tax = tax_override if tax_override is not None else (amount * rate).quantize(Decimal("0.01"))
    inv = {"vendor_invoice_number": number, "invoice_date": inv_date, "po_id": po, "currency": "USD",
           "subtotal_amount": amount, "tax_amount": Decimal(tax),
           "total_amount": amount + Decimal(tax) + Decimal(total_delta),
           "lines": [{"sku": "SKU-ITH-0001", "description": "Laptop", "quantity": qty, "unit_price": price,
                      "tax_code": tax_code, "line_amount": amount}]}
    return {"invoice_id": f"INV-APE01-2026-{n:06d}", "document_id": f"DOC-2026-{n:06d}",
            "received_date": "2026-03-13", "channel": "EMAIL", "content": render(inv, VENDOR, "EMAIL")}


def test_clean_invoice_is_payment_ready():
    d = world().process(doc())
    assert d.codes == [] and d.match_status == "MATCHED" and d.payment_ready
    assert d.approval_roles == ["SYSTEM_AUTO"]            # 1,082.50 <= 10,000
    assert [e["to_state"] for e in d.events][-1] == "PAYMENT_READY"
    assert d.allocations[0]["grn_line_id"] == "GRN-2026-000001-01"


def test_price_within_tolerance_passes_and_above_fails():
    assert world().process(doc(price="102.00")).codes == []          # exactly +2.00%
    d = world().process(doc(price="102.01"))
    assert d.codes == ["PRICE_VARIANCE"] and not d.payment_ready
    assert d.route_queue == "PROCUREMENT"


def test_partial_delivery_billed_in_full():
    assert world(received=6).process(doc(qty=10)).codes == ["QTY_EXCEEDS_RECEIVED"]


def test_partial_delivery_billed_at_received_is_clean():
    assert world(received=6).process(doc(qty=6)).codes == []


def test_invoice_exceeds_po_quantity():
    assert world(received=10).process(doc(qty=12)).codes == ["QTY_EXCEEDS_PO", "QTY_EXCEEDS_RECEIVED"]
    assert world(received=12).process(doc(qty=12)).codes == ["QTY_EXCEEDS_PO"]      # over-receipt


def test_missing_receipt():
    d = world(received=0).process(doc())
    assert d.codes == ["MISSING_RECEIPT"] and d.route_queue == "RECEIVING"


def test_tax_code_and_tax_amount_mismatch():
    assert world().process(doc(tax_code="TX10")).codes == ["TAX_MISMATCH"]
    assert world().process(doc(tax_override="50.00")).codes == ["TAX_MISMATCH"]


def test_total_differs_from_line_sum():
    assert world().process(doc(total_delta="25.00")).codes == ["TOTAL_MISMATCH"]


def test_invoice_date_before_po_date():
    assert world().process(doc(inv_date=date(2026, 2, 20))).codes == ["DATE_BEFORE_PO"]


def test_closed_vendor():
    eng = world(vendor={"status": "CLOSED", "closed_date": "2026-03-11"})
    d = eng.process(doc())
    assert d.codes == ["VENDOR_INACTIVE"] and d.route_queue == "VENDOR_MASTER"


def test_same_invoice_submitted_twice_flags_pair():
    eng = world()
    first = eng.process(doc(n=1))
    second = eng.process(doc(n=2, number="ape0126-0001"))     # re-typed number, same after normalising
    assert first.payment_ready
    assert second.codes == ["DUPLICATE_EXACT"] and second.duplicate_of == first.invoice_id
    assert second.final_state == "DUPLICATE_BLOCKED" and not second.payment_ready


def test_duplicate_invoice_number_with_different_content():
    eng = world()
    eng.process(doc(n=1, qty=5))
    d = eng.process(doc(n=2, qty=4, inv_date=date(2026, 3, 20)))
    assert d.codes == ["DUPLICATE_NUMBER"] and d.duplicate_of == "INV-APE01-2026-000001"


def test_cumulative_billing_across_invoices():
    eng = world(received=10)
    assert eng.process(doc(n=1, qty=6, number="A-1")).codes == []
    assert eng.process(doc(n=2, qty=6, number="A-2")).codes == ["QTY_EXCEEDS_PO", "QTY_EXCEEDS_RECEIVED"]


def test_unparseable_document_is_routed_not_crashed():
    d = world().process({"invoice_id": "INV-APE01-2026-000001", "document_id": "DOC-2026-000001",
                         "received_date": "2026-03-13", "channel": "EMAIL", "content": "garbage"})
    assert d.codes == ["EXTRACTION_FAILED"] and d.final_state == "EXCEPTION_ROUTED"


def test_payment_guard_refuses_blocked_invoice():
    d = Decision(invoice_id="X", document_id="Y", received_date=date(2026, 1, 1))
    d.final_state = "EXCEPTION_ROUTED"
    with pytest.raises(PaymentSafetyError):
        DecisionEngine._mark_payment_ready(d)


def test_goods_invoice_without_po_is_blocked_but_service_invoice_is_allowed():
    """Found by the robustness test: a blank PO reference must not bypass the 3-way match."""
    d = world().process(doc(po=None))
    assert d.codes == ["PO_REQUIRED"] and d.route_queue == "PROCUREMENT" and not d.payment_ready
    svc = doc(po=None)
    svc["content"] = svc["content"].replace("SKU-ITH-0001", "SKU-SRV-0001")
    ok = world().process(svc)
    assert ok.codes == [] and ok.payment_ready and ok.approval_roles == ["DEPT_MANAGER"]   # non-PO needs a human
