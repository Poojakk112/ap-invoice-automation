from collections import Counter

from apflow.config import allocate, load_policy
from apflow.export import export_dataset
from apflow.generator import generate
from apflow.validation import validate


def test_volumes_match_config(tables, policy):
    v = policy.volumes
    assert len(tables["vendors"]) == v["vendors"]
    assert len(tables["purchase_orders"]) == v["purchase_orders"]
    assert len(tables["purchase_order_lines"]) == v["purchase_order_lines"]
    assert len(tables["goods_receipts"]) == v["goods_receipts"]
    assert len(tables["invoices"]) == v["invoices"]


def test_scenario_mix_matches_target(tables, policy):
    got = Counter(g["scenario"] for g in tables["ground_truth"])
    assert dict(got) == {k: c for k, c in allocate(policy.volumes["invoices"], policy.scenario_mix).items() if c}


def test_all_required_edge_cases_present(tables):
    subs = {g["sub_scenario"] for g in tables["ground_truth"]}
    required = {"duplicate_invoice_number", "total_mismatch", "invoice_date_before_po", "partial_delivery",
                "closed_vendor", "tax_mismatch", "exceeds_po_quantity", "same_invoice_submitted_twice",
                "partial_receipt_billed_at_received", "over_receipt_billed_at_po", "non_po"}
    assert required <= subs


def test_po_lines_between_1_and_8(tables):
    per_po = Counter(ln["po_id"] for ln in tables["purchase_order_lines"])
    assert all(1 <= n <= 8 for n in per_po.values())
    assert len(per_po) == len(tables["purchase_orders"])


def test_receipts_cover_full_partial_and_over(tables):
    statuses = Counter(ln["receipt_status"] for ln in tables["purchase_order_lines"])
    assert {"FULL", "PARTIAL", "OVER", "NOT_RECEIVED"} <= set(statuses)


def test_approvals_and_payments_only_for_eligible(tables):
    eligible = {g["invoice_id"] for g in tables["ground_truth"] if g["expected_payment_ready"]}
    assert {a["invoice_id"] for a in tables["approvals"]} == eligible
    assert {p["invoice_id"] for p in tables["payments"]} == eligible


def test_generated_dataset_passes_validation(dataset_dir, policy):
    summary = validate(dataset_dir, policy)
    failed = [c for c in summary["checks"] if c["status"] == "FAIL"]
    assert not failed, failed


def test_same_seed_is_byte_identical(tmp_path):
    p = load_policy(scale=0.1)
    a = export_dataset(generate(p), tmp_path / "a", p, "t")
    b = export_dataset(generate(load_policy(scale=0.1)), tmp_path / "b", p, "t")
    assert a["files"] == b["files"]


def test_different_seed_changes_data():
    a = generate(load_policy(scale=0.1))
    b = generate(load_policy(scale=0.1, seed=1))
    assert [v["vendor_name"] for v in a["vendors"]] != [v["vendor_name"] for v in b["vendors"]]


def test_ground_truth_not_in_input_folder(dataset_dir):
    for f in (dataset_dir / "input").glob("*.csv"):
        header = f.read_text().splitlines()[0]
        assert "expected_" not in header and "scenario" not in header, f.name
    docs = (dataset_dir / "input" / "invoice_documents.jsonl").read_text()
    assert "scenario" not in docs and "expected_" not in docs
