"""What-if simulator: how does the price-tolerance setting change the outcome?

A strict tolerance blocks good invoices (more manual work). A loose tolerance
lets overcharges through (money lost). This replays the same invoices under
several tolerances and measures both sides, using the generator's reference
data (PO price vs billed price) to price the overcharge.
"""

import dataclasses
from decimal import Decimal
from pathlib import Path

from apflow.config import Policy
from apflow.export import read_csv, write_json
from apflow.money import D, q2
from apflow.pipeline.run import decide, load_inputs

TOLERANCES = ["0.00", "0.01", "0.02", "0.03", "0.05", "0.10"]


def run_whatif(data_dir, policy: Policy) -> dict:
    data_dir = Path(data_dir)
    tables = load_inputs(data_dir)
    gt = {r["invoice_id"]: r for r in read_csv(data_dir / "ground_truth" / "ground_truth.csv")}
    po_price = {r["po_line_id"]: D(r["unit_price"]) for r in tables["purchase_order_lines"]}
    overcharge = {}
    for ln in read_csv(data_dir / "reference" / "invoice_lines.csv"):
        if ln["po_line_id"]:
            extra = (D(ln["unit_price"]) - po_price[ln["po_line_id"]]) * int(ln["quantity"])
            overcharge[ln["invoice_id"]] = overcharge.get(ln["invoice_id"], Decimal("0")) + max(extra, Decimal("0"))
    n = len(gt)
    current = policy.price_tolerance_pct
    rows = []
    for tol in sorted(set(TOLERANCES) | {str(current)}, key=Decimal):
        pol = dataclasses.replace(policy, price_tolerance_pct=Decimal(tol))
        decisions = decide(tables, pol)
        ready = [d for d in decisions if d.payment_ready]
        blocked = [d for d in decisions if not d.payment_ready]
        price_flags = sum("PRICE_VARIANCE" in d.codes for d in decisions)
        leaked = sum((overcharge.get(d.invoice_id, Decimal("0")) for d in ready), Decimal("0"))
        stopped = sum((overcharge.get(d.invoice_id, Decimal("0")) for d in blocked
                       if "PRICE_VARIANCE" in d.codes), Decimal("0"))
        false_blocks = sum(1 for d in blocked if gt[d.invoice_id]["expected_payment_ready"] == "true")
        missed = sum(1 for d in ready if overcharge.get(d.invoice_id, Decimal("0")) > 0
                     and gt[d.invoice_id]["scenario"] == "price_variance")
        rows.append({"tolerance_pct": float(Decimal(tol) * 100), "current_policy": Decimal(tol) == current,
                     "touchless_rate": round(len(ready) / n, 4), "payment_ready": len(ready),
                     "needs_human": len(blocked), "price_variance_flags": price_flags,
                     "good_invoices_blocked": false_blocks, "price_variances_missed": missed,
                     "overcharge_paid_usd": str(q2(leaked)), "overcharge_stopped_usd": str(q2(stopped))})
    return {"invoices": n, "current_tolerance_pct": float(current * 100), "rows": rows,
            "reading_guide": "Stricter tolerance: more good invoices need a person. Looser tolerance: more overcharge is paid. "
                             "'Good invoices blocked' counts invoices the ground truth marks payable that were stopped. "
                             "Note: the synthetic price variances are either under 1.5% or over 3%, so 2% and 3% give "
                             "identical results; real data would be smoother."}


def whatif_markdown(r: dict) -> str:
    lines = ["# What-if: price tolerance", "", r["reading_guide"], "",
             "| Tolerance | Touchless | Need a person | Good invoices blocked | Variances missed | Overcharge paid | Overcharge stopped |",
             "|---|---|---|---|---|---|---|"]
    for x in r["rows"]:
        mark = " (current)" if x["current_policy"] else ""
        lines.append(f"| {x['tolerance_pct']:.0f}%{mark} | {x['touchless_rate']:.1%} | {x['needs_human']} | "
                     f"{x['good_invoices_blocked']} | {x['price_variances_missed']} | "
                     f"${float(x['overcharge_paid_usd']):,.2f} | ${float(x['overcharge_stopped_usd']):,.2f} |")
    return "\n".join(lines) + "\n"


def save(r: dict, out_dir: Path):
    write_json(out_dir / "whatif.json", r)
    (out_dir / "whatif.md").write_text(whatif_markdown(r), encoding="utf-8", newline="\n")
