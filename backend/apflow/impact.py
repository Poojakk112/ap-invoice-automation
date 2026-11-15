"""Business impact estimate.

Measured numbers come from the pipeline run. Everything that is an assumption
(minutes per invoice, hourly cost, how often people miss a problem) lives in
config/assumptions.json and is labelled as an assumption in the output.
"""

import json
from decimal import Decimal
from pathlib import Path

from apflow.config import BACKEND_ROOT
from apflow.export import write_json

ASSUMPTIONS_PATH = BACKEND_ROOT / "config" / "assumptions.json"


def load_assumptions(path=None) -> dict:
    return json.loads(Path(path or ASSUMPTIONS_PATH).read_text(encoding="utf-8"))


def compute_impact(metrics: dict, assumptions: dict | None = None) -> dict:
    a = assumptions or load_assumptions()
    k = metrics["kpis"]
    invoices = k["invoices_processed"]
    ready = k["payment_ready_count"]
    exceptions = invoices - ready
    rate = Decimal(str(a["loaded_cost_per_hour_usd"]))

    before_min = invoices * a["minutes_per_invoice_manual_processing"] + \
        exceptions * a["minutes_per_exception_manual_investigation"]
    after_min = ready * a["minutes_per_invoice_touchless_spot_check"] + \
        exceptions * a["minutes_per_exception_with_guided_reason"]
    saved_hours = (before_min - after_min) / 60
    labour_saved = Decimal(str(saved_hours)) * rate
    fte = saved_hours / a["working_hours_per_fte_year"]

    dup = Decimal(k["duplicate_payments_prevented_value"])
    over = Decimal(k["overbilling_prevented_value"])
    leak_avoided = dup * Decimal(str(a["manual_process_miss_rate_duplicates"])) + \
        over * Decimal(str(a["manual_process_miss_rate_overbilling"]))

    rows = [
        {"item": "Invoices processed", "value": f"{invoices:,}", "basis": "measured"},
        {"item": "Touchless (no manual matching)", "value": f"{ready:,} ({ready / invoices:.0%})", "basis": "measured"},
        {"item": "Invoices needing a person", "value": f"{exceptions:,}", "basis": "measured"},
        {"item": "Manual effort before (hours)", "value": f"{before_min / 60:,.0f}", "basis": "assumption x measured volume"},
        {"item": "Effort with automation (hours)", "value": f"{after_min / 60:,.0f}", "basis": "assumption x measured volume"},
        {"item": "Hours saved", "value": f"{saved_hours:,.0f}", "basis": "derived"},
        {"item": "Full-time equivalents freed", "value": f"{fte:.2f}", "basis": "derived"},
        {"item": "Labour cost saved", "value": f"${labour_saved:,.0f}", "basis": "derived (assumed hourly cost)"},
        {"item": "Duplicate invoices blocked (value)", "value": f"${dup:,.0f}", "basis": "measured on synthetic data"},
        {"item": "Over-billing blocked (value)", "value": f"${over:,.0f}", "basis": "measured on synthetic data"},
        {"item": "Expected leakage avoided vs manual process", "value": f"${leak_avoided:,.0f}",
         "basis": "assumption: share a manual process would miss"},
    ]
    return {"rows": rows, "assumptions": {k: v for k, v in a.items() if not k.startswith("_")},
            "hours_saved": round(saved_hours, 1), "fte_freed": round(fte, 2),
            "labour_saved_usd": str(round(labour_saved)), "leakage_avoided_usd": str(round(leak_avoided))}


def impact_markdown(r: dict, dataset: str) -> str:
    lines = [f"# Business impact estimate ({dataset} dataset)", "",
             "Dollar and hour figures mix **measured** results with **assumptions**. The assumptions are in "
             "`backend/config/assumptions.json` and must be replaced with the customer's own numbers. "
             "Duplicate and over-billing values come from synthetic data, so they show how the control works, "
             "not what a real company would save.", "",
             "| Item | Value | Basis |", "|---|---|---|"]
    lines += [f"| {x['item']} | {x['value']} | {x['basis']} |" for x in r["rows"]]
    lines += ["", "## Assumptions used", "", "| Assumption | Value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in r["assumptions"].items()]
    return "\n".join(lines) + "\n"


def save(r: dict, out_dir: Path, dataset: str):
    write_json(out_dir / "impact.json", r)
    (out_dir / "impact.md").write_text(impact_markdown(r, dataset), encoding="utf-8", newline="\n")
