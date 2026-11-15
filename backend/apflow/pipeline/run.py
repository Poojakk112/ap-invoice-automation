"""Run the automation over a dataset and persist every decision and event."""

import json
import sqlite3
from pathlib import Path

from apflow.config import Policy
from apflow.export import read_csv, serialise, write_csv
from apflow.pipeline.engine import Context, DecisionEngine, severity
from apflow.policy import EXCEPTIONS
from apflow.schema import INPUT_TABLES, ddl

DECISION_COLUMNS = [
    "invoice_id", "document_id", "layout", "vendor_id", "po_id", "vendor_invoice_number", "invoice_date",
    "received_date", "stated_total", "computed_total", "match_status", "exceptions", "primary_exception",
    "route_queue", "duplicate_of", "approval_tier", "approval_roles", "final_state", "payment_ready",
    "due_date", "scheduled_payment_date", "payment_method", "explanation",
]
EXCEPTION_COLUMNS = ["exception_id", "invoice_id", "code", "severity", "queue", "line_ref", "expected", "actual",
                     "value_at_risk", "message"]
EVENT_COLUMNS = ["event_id", "invoice_id", "sequence", "event_time", "from_state", "to_state", "actor", "reason"]
ALLOC_COLUMNS = ["allocation_id", "invoice_id", "invoice_line_number", "po_line_id", "grn_line_id", "quantity"]
APPROVAL_COLUMNS = ["invoice_id", "level", "approver_role", "decision", "decided_date", "simulated"]
EXTRACT_COLUMNS = ["invoice_id", "layout", "vendor_tax_id", "vendor_invoice_number", "invoice_date", "po_number",
                   "currency", "subtotal", "tax_total", "stated_total", "line_count"]
EXTRACT_LINE_COLUMNS = ["invoice_id", "line_number", "sku", "description", "quantity", "unit_price", "tax_code",
                        "line_amount"]


def load_inputs(data_dir: Path) -> dict:
    """Only master data + documents. Reference and ground-truth folders are not touched."""
    tables = {t.name: read_csv(data_dir / "input" / f"{t.name}.csv") for t in INPUT_TABLES}
    docs = (data_dir / "input" / "invoice_documents.jsonl").read_text(encoding="utf-8").splitlines()
    tables["_documents"] = sorted((json.loads(x) for x in docs if x),
                                  key=lambda d: (d["received_date"], d["invoice_id"].rsplit("-", 1)[1]))
    return tables


def run_pipeline(data_dir, out_dir, policy: Policy) -> dict:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = load_inputs(data_dir)
    ctx = Context(tables, policy)
    engine = DecisionEngine(ctx, policy)
    decisions = [engine.process(doc) for doc in tables["_documents"]]

    rows = {k: [] for k in ("decisions", "exceptions", "invoice_events", "match_allocations",
                            "approval_decisions", "extracted_invoices", "extracted_invoice_lines")}
    for d in decisions:
        rows["decisions"].append({
            "invoice_id": d.invoice_id, "document_id": d.document_id, "layout": d.layout, "vendor_id": d.vendor_id,
            "po_id": d.po_id, "vendor_invoice_number": d.vendor_invoice_number, "invoice_date": d.invoice_date,
            "received_date": d.received_date, "stated_total": d.stated_total, "computed_total": d.computed_total,
            "match_status": d.match_status, "exceptions": "|".join(d.codes), "primary_exception": d.primary,
            "route_queue": d.route_queue, "duplicate_of": d.duplicate_of, "approval_tier": d.approval_tier,
            "approval_roles": "|".join(d.approval_roles), "final_state": d.final_state,
            "payment_ready": d.payment_ready, "due_date": d.due_date,
            "scheduled_payment_date": d.scheduled_payment_date, "payment_method": d.payment_method,
            "explanation": d.explanation()})
        for i in d.issues:
            rows["exceptions"].append({
                "exception_id": f"EXC-{len(rows['exceptions']) + 1:07d}", "invoice_id": d.invoice_id,
                "code": i.code, "severity": severity(i.code), "queue": EXCEPTIONS[i.code][1],
                "line_ref": i.line_ref, "expected": i.expected, "actual": i.actual,
                "value_at_risk": i.value_at_risk, "message": i.message})
        for e in d.events:
            rows["invoice_events"].append({"event_id": f"IEV-{len(rows['invoice_events']) + 1:07d}", **e})
        for a in d.allocations:
            rows["match_allocations"].append({"allocation_id": f"ALC-{len(rows['match_allocations']) + 1:07d}", **a})
        rows["approval_decisions"] += d.approvals
        if d.extracted:
            x = d.extracted
            rows["extracted_invoices"].append({
                "invoice_id": d.invoice_id, "layout": x.layout, "vendor_tax_id": x.vendor_tax_id,
                "vendor_invoice_number": x.vendor_invoice_number, "invoice_date": x.invoice_date,
                "po_number": x.po_number, "currency": x.currency, "subtotal": x.subtotal, "tax_total": x.tax_total,
                "stated_total": x.stated_total, "line_count": len(x.lines)})
            for ln in x.lines:
                rows["extracted_invoice_lines"].append({"invoice_id": d.invoice_id, **ln.__dict__})

    columns = {"decisions": DECISION_COLUMNS, "exceptions": EXCEPTION_COLUMNS, "invoice_events": EVENT_COLUMNS,
               "match_allocations": ALLOC_COLUMNS, "approval_decisions": APPROVAL_COLUMNS,
               "extracted_invoices": EXTRACT_COLUMNS, "extracted_invoice_lines": EXTRACT_LINE_COLUMNS}
    string_rows = {}
    for name, cols in columns.items():
        string_rows[name] = serialise(rows[name], cols)
        write_csv(out_dir / f"{name}.csv", string_rows[name], cols)
    ready = [r for r in string_rows["decisions"] if r["payment_ready"] == "true"]
    write_csv(out_dir / "payment_ready.csv", ready, DECISION_COLUMNS)
    build_sqlite(out_dir / "ap_automation.db", tables, string_rows, columns)
    return {"decisions": decisions, "rows": string_rows}


def build_sqlite(path: Path, inputs: dict, outputs: dict, columns: dict):
    """One queryable database for analysts: master data + every pipeline output."""
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        for t in INPUT_TABLES:
            con.execute(ddl(t, "sqlite"))
            con.executemany(f"INSERT INTO {t.name} VALUES ({','.join('?' * len(t.columns))})",
                            [[r[c] or None for c in t.columns] for r in inputs[t.name]])
        for name, cols in columns.items():
            con.execute(f"CREATE TABLE {name} ({', '.join(c + ' TEXT' for c in cols)})")
            con.executemany(f"INSERT INTO {name} VALUES ({','.join('?' * len(cols))})",
                            [[r[c] for c in cols] for r in outputs[name]])
        con.execute("CREATE VIEW exception_queue AS SELECT queue, code, COUNT(*) AS n, "
                    "ROUND(SUM(CAST(value_at_risk AS REAL)),2) AS value_at_risk FROM exceptions "
                    "GROUP BY queue, code ORDER BY n DESC")
        con.commit()
    finally:
        con.close()
