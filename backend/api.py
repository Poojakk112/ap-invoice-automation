"""Web API for the AP automation dashboard (FastAPI).

Start:   cd backend
         python -m uvicorn api:app --reload
Open:    http://127.0.0.1:8000        (dashboard)
         http://127.0.0.1:8000/docs   (interactive API documentation)

The API reads the pipeline results from the SQLite database
output/<dataset>/ap_automation.db plus metrics.json. It never reads ground
truth for decisions; ground truth is only used by the evaluation metrics.
"""

import json
import sqlite3
from argparse import Namespace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from apflow import cli
from apflow.config import ROOT

DATA_ROOT = ROOT / "data"
OUTPUT_ROOT = ROOT / "output"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="AP Invoice Automation API", version="1.0.0",
              description="Invoice intake, extraction, 3-way match, exception routing and payment readiness.")


# ------------------------------------------------------------------ helpers
def _out_dir(dataset: str) -> Path:
    if not dataset.replace("_", "").replace(".", "").isalnum():
        raise HTTPException(400, "invalid dataset name")
    d = OUTPUT_ROOT / dataset
    if not (d / "ap_automation.db").exists():
        raise HTTPException(404, f"dataset '{dataset}' has not been run yet - POST /api/pipeline/run first")
    return d


def _query(dataset: str, sql: str, params=()) -> list:
    con = sqlite3.connect(_out_dir(dataset) / "ap_automation.db")
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/datasets")
def datasets():
    """Datasets that have pipeline output, with their seed/scale."""
    out = []
    for d in sorted(OUTPUT_ROOT.glob("*/ap_automation.db")):
        name = d.parent.name
        manifest = _json(DATA_ROOT / name / "manifest.json") or {}
        out.append({"name": name, "seed": manifest.get("seed"), "scale": manifest.get("scale"),
                    "invoices": manifest.get("row_counts", {}).get("invoices")})
    return out


@app.get("/api/summary")
def summary(dataset: str = "full"):
    """KPIs, acceptance criteria, detection metrics and validation result."""
    out = _out_dir(dataset)
    validation = _json(DATA_ROOT / dataset / "validation_summary.json") or {}
    return {"dataset": dataset, "manifest": _json(DATA_ROOT / dataset / "manifest.json"),
            "metrics": _json(out / "metrics.json"),
            "validation": {k: validation.get(k) for k in ("passed", "checks_total", "checks_failed")},
            "reproducibility": {k: v for k, v in (_json(out / "reproducibility_report.json") or {}).items()
                                if k in ("identical", "files_compared", "seed")}}


@app.get("/api/invoices")
def invoices(dataset: str = "full",
             state: str | None = Query(None, description="PAYMENT_READY, EXCEPTION_ROUTED, DUPLICATE_BLOCKED"),
             queue: str | None = None,
             exception: str | None = None,
             search: str | None = Query(None, description="invoice id, vendor id, PO or vendor invoice number"),
             limit: int = Query(50, ge=1, le=500),
             offset: int = Query(0, ge=0)):
    """Paged invoice list with filters."""
    where, params = [], []
    if state:
        where.append("final_state = ?")
        params.append(state)
    if queue:
        where.append("route_queue = ?")
        params.append(queue)
    if exception:
        where.append("('|' || exceptions || '|') LIKE ?")
        params.append(f"%|{exception}|%")
    if search:
        where.append("(invoice_id LIKE ? OR vendor_id LIKE ? OR po_id LIKE ? OR vendor_invoice_number LIKE ?)")
        params += [f"%{search}%"] * 4
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = "(SELECT d.*, v.vendor_name FROM decisions d LEFT JOIN vendors v USING (vendor_id))"
    total = _query(dataset, f"SELECT COUNT(*) AS n FROM {base}{clause}", params)[0]["n"]
    rows = _query(dataset, f"SELECT * FROM {base}{clause} "
                           f"ORDER BY CAST(substr(invoice_id, -6) AS INTEGER) LIMIT ? OFFSET ?",
                  params + [limit, offset])
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@app.get("/api/invoices/{invoice_id}")
def invoice_detail(invoice_id: str, dataset: str = "full"):
    """Everything about one invoice: decision, exceptions, audit trail, lines, receipts, raw document."""
    rows = _query(dataset, "SELECT d.*, v.vendor_name, v.status AS vendor_status FROM decisions d "
                           "LEFT JOIN vendors v USING (vendor_id) WHERE d.invoice_id = ?", (invoice_id,))
    if not rows:
        raise HTTPException(404, f"invoice {invoice_id} not found")
    doc = None
    docs_path = DATA_ROOT / dataset / "input" / "invoice_documents.jsonl"
    if docs_path.exists():
        with docs_path.open(encoding="utf-8") as fh:
            for line in fh:
                if f'"invoice_id": "{invoice_id}"' in line:
                    doc = json.loads(line)
                    break
    return {
        "decision": rows[0],
        "exceptions": _query(dataset, "SELECT * FROM exceptions WHERE invoice_id = ? ORDER BY exception_id", (invoice_id,)),
        "events": _query(dataset, "SELECT * FROM invoice_events WHERE invoice_id = ? "
                                  "ORDER BY CAST(sequence AS INTEGER)", (invoice_id,)),
        "lines": _query(dataset, "SELECT * FROM extracted_invoice_lines WHERE invoice_id = ? "
                                 "ORDER BY CAST(line_number AS INTEGER)", (invoice_id,)),
        "allocations": _query(dataset, "SELECT * FROM match_allocations WHERE invoice_id = ?", (invoice_id,)),
        "approvals": _query(dataset, "SELECT * FROM approval_decisions WHERE invoice_id = ? "
                                     "ORDER BY CAST(level AS INTEGER)", (invoice_id,)),
        "document": doc,
    }


@app.get("/api/queues")
def queues(dataset: str = "full"):
    """Open work queues with exception counts and value at risk."""
    return _query(dataset, "SELECT * FROM exception_queue")


def _report(dataset: str, name: str):
    data = _json(_out_dir(dataset) / name)
    if data is None:
        raise HTTPException(404, f"{name} not found - run: python -m apflow all")
    return data


@app.get("/api/whatif")
def whatif(dataset: str = "full"):
    """Price-tolerance what-if: touchless rate vs good invoices blocked vs overcharge paid."""
    return _report(dataset, "whatif.json")


@app.get("/api/robustness")
def robustness(dataset: str = "full"):
    """Damaged-document test: how each kind of damage is handled; unsafe payments must be 0."""
    return _report(dataset, "robustness.json")


@app.get("/api/impact")
def impact(dataset: str = "full"):
    """Business impact estimate; every row says whether it is measured or an assumption."""
    return _report(dataset, "impact.json")


class RunRequest(BaseModel):
    scale: float = Field(0.1, gt=0, le=2.0, description="1.0 = full volume")
    seed: int | None = None
    name: str = Field("starter", pattern=r"^[A-Za-z0-9_]+$")


@app.post("/api/pipeline/run")
def run_pipeline(req: RunRequest):
    """Generate -> validate -> run -> evaluate -> reproduce, then return the new summary."""
    args = Namespace(scale=req.scale, seed=req.seed, name=req.name, policy=None)
    for step in (cli.cmd_generate, cli.cmd_validate, cli.cmd_run, cli.cmd_evaluate, cli.cmd_whatif,
                 cli.cmd_robustness, cli.cmd_impact, cli.cmd_reproduce):
        if step(args) != 0:
            raise HTTPException(500, f"step {step.__name__} failed - see server log")
    return summary(req.name)


# ------------------------------------------------------------------ frontend
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
