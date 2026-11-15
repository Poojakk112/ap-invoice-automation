"""End-to-end: generate -> run -> evaluate on the starter dataset, plus
negative tests proving validation catches corrupted data."""

import csv

from apflow.evaluation import evaluate
from apflow.export import read_csv, write_csv
from apflow.policy import INVOICE_TRANSITIONS
from apflow.validation import validate


def test_acceptance_criteria_all_pass(dataset_dir, pipeline_out):
    m = evaluate(dataset_dir, pipeline_out)
    assert m["safety"]["blocked_invoices_marked_payment_ready"] == 0
    for criterion, rate in m["acceptance"].items():
        assert rate == 1.0, criterion
    assert m["duplicates"]["pairs_correct"] == m["duplicates"]["labelled"]
    assert m["duplicates"]["false_positives"] == 0


def test_every_invoice_event_history_is_a_legal_lifecycle(pipeline_out):
    by_inv = {}
    for e in read_csv(pipeline_out / "invoice_events.csv"):
        by_inv.setdefault(e["invoice_id"], []).append(e)
    for inv, events in by_inv.items():
        prev = None
        for e in sorted(events, key=lambda x: int(x["sequence"])):
            assert e["to_state"] in INVOICE_TRANSITIONS[prev], (inv, prev, e["to_state"])
            prev = e["to_state"]


def test_no_payment_ready_invoice_has_exceptions(pipeline_out):
    for d in read_csv(pipeline_out / "decisions.csv"):
        if d["payment_ready"] == "true":
            assert d["exceptions"] == "" and d["final_state"] == "PAYMENT_READY"


def test_sqlite_database_is_queryable(pipeline_out):
    import sqlite3
    con = sqlite3.connect(pipeline_out / "ap_automation.db")
    n = con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    q = con.execute("SELECT SUM(n) FROM exception_queue").fetchone()[0]
    con.close()
    assert n == 200 and q > 0


def _rewrite(path, mutate):
    rows = read_csv(path)
    mutate(rows)
    write_csv(path, rows, list(rows[0]))


def _failed(summary):
    return {c["check"] for c in summary["checks"] if c["status"] == "FAIL"}


def test_validation_catches_duplicate_primary_key(dataset_copy, policy):
    _rewrite(dataset_copy / "input" / "vendors.csv", lambda r: r[1].update(vendor_id=r[0]["vendor_id"]))
    assert any("primary key" in c for c in _failed(validate(dataset_copy, policy)))


def test_validation_catches_broken_foreign_key(dataset_copy, policy):
    _rewrite(dataset_copy / "input" / "goods_receipt_lines.csv", lambda r: r[0].update(po_line_id="PO-2026-999999-01"))
    assert any("goods_receipt_lines.po_line_id" in c for c in _failed(validate(dataset_copy, policy)))


def test_validation_catches_unlabelled_arithmetic_error(dataset_copy, policy):
    gt = {g["invoice_id"]: g for g in read_csv(dataset_copy / "ground_truth" / "ground_truth.csv")}

    def corrupt(rows):
        row = next(r for r in rows if gt[r["invoice_id"]]["scenario"] == "clean")
        row["total_amount"] = f"{float(row['total_amount']) + 1:.2f}"
    _rewrite(dataset_copy / "reference" / "invoices.csv", corrupt)
    assert any("grand totals" in c for c in _failed(validate(dataset_copy, policy)))


def test_validation_catches_bad_enum(dataset_copy, policy):
    _rewrite(dataset_copy / "input" / "purchase_order_lines.csv", lambda r: r[0].update(tax_code="TX99"))
    assert any("allowed values" in c for c in _failed(validate(dataset_copy, policy)))
