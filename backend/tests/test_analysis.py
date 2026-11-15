"""Tests for the what-if simulator, robustness test and impact estimate."""

import pytest

from apflow.config import load_policy
from apflow.impact import compute_impact
from apflow.robustness import NOISE_DESCRIPTIONS, damage, run_robustness
from apflow.whatif import run_whatif


@pytest.fixture(scope="module")
def whatif(dataset_dir, policy):
    return run_whatif(dataset_dir, policy)


def test_whatif_current_policy_matches_pipeline(whatif, pipeline_out):
    from apflow.export import read_csv
    ready = sum(d["payment_ready"] == "true" for d in read_csv(pipeline_out / "decisions.csv"))
    current = next(r for r in whatif["rows"] if r["current_policy"])
    assert current["payment_ready"] == ready
    assert current["good_invoices_blocked"] == 0 and current["price_variances_missed"] == 0


def test_whatif_trade_off_is_monotonic(whatif):
    rows = whatif["rows"]
    touchless = [r["touchless_rate"] for r in rows]
    paid = [float(r["overcharge_paid_usd"]) for r in rows]
    blocked_good = [r["good_invoices_blocked"] for r in rows]
    assert touchless == sorted(touchless)            # looser -> more touchless
    assert paid == sorted(paid)                      # looser -> more overcharge paid
    assert blocked_good == sorted(blocked_good, reverse=True)   # looser -> fewer good invoices blocked


def test_damage_functions_change_the_document():
    text = ("TAX INVOICE\nSupplier: X\nInvoice No: A-1\n"
            "1 | SKU-OFF-0001 | Pens | 10 | 125.50 | TX8 | 1,255.00\nTotal Due: 1,358.54")
    for kind in NOISE_DESCRIPTIONS:
        out = damage(text, kind)
        if kind == "missing_po_reference":
            assert out is None                       # no PO line in this document
        else:
            assert out is not None and out != text, kind
    assert "Total Due" not in damage(text, "missing_total")


def test_no_damage_ever_causes_an_unsafe_payment(dataset_dir, policy):
    r = run_robustness(dataset_dir, policy, sample=40)
    assert r["documents_damaged"] > 0
    assert r["unsafe_payments"] == 0, {k: v["unsafe_examples"] for k, v in r["by_damage_type"].items()}


def test_messy_whitespace_is_harmless(dataset_dir, policy):
    r = run_robustness(dataset_dir, policy, sample=40)
    w = r["by_damage_type"]["messy_whitespace"]["caught_by"]
    assert "EXTRACTION_FAILED" not in w


def test_impact_uses_assumptions_and_measured_values():
    metrics = {"kpis": {"invoices_processed": 100, "payment_ready_count": 70,
                        "duplicate_payments_prevented_value": "1000.00", "overbilling_prevented_value": "500.00"}}
    a = {"minutes_per_invoice_manual_processing": 10, "minutes_per_exception_manual_investigation": 30,
         "minutes_per_invoice_touchless_spot_check": 1, "minutes_per_exception_with_guided_reason": 10,
         "loaded_cost_per_hour_usd": 60, "working_hours_per_fte_year": 1000,
         "manual_process_miss_rate_duplicates": 0.5, "manual_process_miss_rate_overbilling": 0.2}
    r = compute_impact(metrics, a)
    # before: 100*10 + 30*30 = 1900 min; after: 70*1 + 30*10 = 370 min -> 1530 min = 25.5 h
    assert r["hours_saved"] == 25.5
    assert r["fte_freed"] == 0.03
    assert r["labour_saved_usd"] == "1530"
    assert r["leakage_avoided_usd"] == "600"          # 1000*0.5 + 500*0.2
    assert any(x["basis"].startswith("assumption") for x in r["rows"])


def test_assumptions_file_is_labelled():
    import json
    from apflow.impact import ASSUMPTIONS_PATH
    assert "ASSUMPTIONS" in json.loads(ASSUMPTIONS_PATH.read_text())["_note"]
