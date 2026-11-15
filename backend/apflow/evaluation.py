"""Evaluation harness: scores pipeline decisions against ground truth and the
structured invoice source, and checks the per-invoice acceptance criteria:

    1. extracted fields match source
    2. line arithmetic and tax reconcile (pipeline agrees with labels)
    3. duplicate detection flags the correct pair
    4. three-way match and approval outcome agree with policy
    5. no blocked invoice is marked payment-ready   (hard safety gate)
"""

from decimal import Decimal
from pathlib import Path

from apflow.export import read_csv, write_csv, write_json
from apflow.money import D
from apflow.policy import BLOCKED_STATES, PRECEDENCE

HEADER_FIELDS = [("vendor_invoice_number", "vendor_invoice_number"), ("invoice_date", "invoice_date"),
                 ("po_number", "po_id"), ("currency", "currency"), ("subtotal", "subtotal_amount"),
                 ("tax_total", "tax_amount"), ("stated_total", "total_amount"), ("line_count", "line_count")]
LINE_FIELDS = ["sku", "description", "quantity", "unit_price", "tax_code", "line_amount"]
ARITH_CODES = {"TOTAL_MISMATCH", "TAX_MISMATCH"}


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return D(a) == D(b)
    except Exception:
        return False


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def evaluate(data_dir, out_dir) -> dict:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    gt = {r["invoice_id"]: r for r in read_csv(data_dir / "ground_truth" / "ground_truth.csv")}
    src = {r["invoice_id"]: r for r in read_csv(data_dir / "reference" / "invoices.csv")}
    vendors = {r["vendor_id"]: r for r in read_csv(data_dir / "input" / "vendors.csv")}
    src_lines = {}
    for r in read_csv(data_dir / "reference" / "invoice_lines.csv"):
        src_lines.setdefault(r["invoice_id"], []).append(r)
    dec = {r["invoice_id"]: r for r in read_csv(out_dir / "decisions.csv")}
    ext = {r["invoice_id"]: r for r in read_csv(out_dir / "extracted_invoices.csv")}
    ext_lines = {}
    for r in read_csv(out_dir / "extracted_invoice_lines.csv"):
        ext_lines.setdefault(r["invoice_id"], []).append(r)
    exc = read_csv(out_dir / "exceptions.csv")

    # ---------------- extraction accuracy per field
    field_hits = {f: 0 for f, _ in HEADER_FIELDS + [("vendor_id", "")] + [(f"line.{x}", "") for x in LINE_FIELDS]}
    field_total = dict.fromkeys(field_hits, 0)
    extraction_ok = {}
    for iid, s in src.items():
        e, ok = ext.get(iid), True
        for f, sf in HEADER_FIELDS:
            field_total[f] += 1
            hit = e is not None and _same(e[f], s[sf] or "")
            field_hits[f] += hit
            ok &= hit
        field_total["vendor_id"] += 1
        hit = e is not None and vendors[s["vendor_id"]]["tax_id"] == e["vendor_tax_id"] and dec[iid]["vendor_id"] == s["vendor_id"]
        field_hits["vendor_id"] += hit
        ok &= hit
        el = sorted(ext_lines.get(iid, []), key=lambda r: int(r["line_number"]))
        sl = sorted(src_lines[iid], key=lambda r: int(r["line_number"]))
        for i, sline in enumerate(sl):
            for x in LINE_FIELDS:
                field_total[f"line.{x}"] += 1
                hit = i < len(el) and _same(el[i][x], sline[x])
                field_hits[f"line.{x}"] += hit
                ok &= hit
        extraction_ok[iid] = ok
    extraction = {f: round(field_hits[f] / field_total[f], 4) for f in field_hits}

    # ---------------- exception detection (multi-label)
    codes = sorted({c for r in gt.values() for c in r["expected_exceptions"].split("|") if c} |
                   {c for r in dec.values() for c in r["exceptions"].split("|") if c}, key=PRECEDENCE.index)
    per_code = {}
    for c in codes:
        tp = fp = fn = 0
        for iid, g in gt.items():
            exp = c in g["expected_exceptions"].split("|")
            got = c in dec[iid]["exceptions"].split("|")
            tp += exp and got
            fp += got and not exp
            fn += exp and not got
        p, r, f = prf(tp, fp, fn)
        per_code[c] = {"support": tp + fn, "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f}

    # ---------------- acceptance per invoice
    accept_rows, confusion = [], {}
    agg = dict.fromkeys(["extraction", "arithmetic", "duplicate", "match", "approval", "payment_safe", "all"], 0)
    blocked_but_ready = 0
    for iid, g in gt.items():
        d = dec[iid]
        exp, got = set(filter(None, g["expected_exceptions"].split("|"))), set(filter(None, d["exceptions"].split("|")))
        arithmetic_ok = (exp & ARITH_CODES) == (got & ARITH_CODES)
        if g["scenario"] == "duplicate":
            duplicate_ok = d["duplicate_of"] == g["duplicate_of_invoice_id"] and d["primary_exception"] == g["expected_primary_exception"]
        else:
            duplicate_ok = d["duplicate_of"] == ""
        match_ok = (d["match_status"] == g["expected_match_status"] and exp == got
                    and d["route_queue"] == g["expected_route_queue"])
        approval_ok = d["approval_roles"] == g["expected_approval_roles"]
        ready = d["payment_ready"] == "true"
        blocked = d["final_state"] in BLOCKED_STATES or bool(got)
        if blocked and ready:
            blocked_but_ready += 1
        payment_safe = not (blocked and ready) and ready == (g["expected_payment_ready"] == "true")
        checks = [extraction_ok[iid], arithmetic_ok, duplicate_ok, match_ok, approval_ok, payment_safe]
        for k, v in zip(["extraction", "arithmetic", "duplicate", "match", "approval", "payment_safe"], checks):
            agg[k] += v
        agg["all"] += all(checks)
        accept_rows.append({"invoice_id": iid, "scenario": g["scenario"], "sub_scenario": g["sub_scenario"],
                            "expected_exceptions": g["expected_exceptions"], "pipeline_exceptions": d["exceptions"],
                            "extraction_ok": extraction_ok[iid], "arithmetic_ok": arithmetic_ok,
                            "duplicate_ok": duplicate_ok, "match_ok": match_ok, "approval_ok": approval_ok,
                            "payment_safe": payment_safe, "passed": all(checks)})
        key = (g["expected_primary_exception"] or "CLEAN", d["primary_exception"] or "CLEAN")
        confusion[key] = confusion.get(key, 0) + 1
    n = len(gt)
    acceptance = {k: round(v / n, 4) for k, v in agg.items()}
    write_csv(out_dir / "acceptance_by_invoice.csv",
              [{k: str(v).lower() if isinstance(v, bool) else v for k, v in r.items()} for r in accept_rows],
              list(accept_rows[0]))

    # ---------------- duplicate pair accuracy
    dup_gt = [g for g in gt.values() if g["scenario"] == "duplicate"]
    dup_pairs_correct = sum(dec[g["invoice_id"]]["duplicate_of"] == g["duplicate_of_invoice_id"] for g in dup_gt)
    dup_false_pos = sum(1 for iid, d in dec.items() if d["duplicate_of"] and gt[iid]["scenario"] != "duplicate")

    # ---------------- business KPIs
    ready = [d for d in dec.values() if d["payment_ready"] == "true"]
    by_queue, by_vendor, risk = {}, {}, {}
    for d in dec.values():
        if d["route_queue"]:
            by_queue[d["route_queue"]] = by_queue.get(d["route_queue"], 0) + 1
            by_vendor[d["vendor_id"]] = by_vendor.get(d["vendor_id"], 0) + 1
    for e in exc:
        risk[e["code"]] = risk.get(e["code"], Decimal("0")) + D(e["value_at_risk"])
    top_vendors = sorted(by_vendor.items(), key=lambda x: (-x[1], x[0]))[:10]
    kpis = {
        "invoices_processed": n,
        "straight_through_rate": round(len(ready) / n, 4),
        "exception_rate": round(sum(1 for d in dec.values() if d["exceptions"]) / n, 4),
        "payment_ready_count": len(ready),
        "payment_ready_value": str(sum((D(d["stated_total"]) for d in ready), Decimal("0"))),
        "blocked_value": str(sum((D(d["stated_total"]) for d in dec.values() if d["payment_ready"] != "true"), Decimal("0"))),
        "duplicate_payments_prevented_value": str(risk.get("DUPLICATE_EXACT", Decimal("0")) + risk.get("DUPLICATE_NUMBER", Decimal("0"))),
        "overbilling_prevented_value": str(sum((risk.get(c, Decimal("0")) for c in
                                               ("PRICE_VARIANCE", "QTY_EXCEEDS_PO", "QTY_EXCEEDS_RECEIVED")), Decimal("0"))),
        "value_at_risk_by_code": {k: str(v) for k, v in sorted(risk.items())},
        "exceptions_by_queue": dict(sorted(by_queue.items())),
        "top_exception_vendors": [{"vendor_id": v, "vendor_name": vendors[v]["vendor_name"], "exceptions": c}
                                  for v, c in top_vendors],
        "approval_tiers": {t: sum(1 for d in ready if d["approval_tier"] == t) for t in ("1", "2", "3")},
    }

    metrics = {
        "acceptance": acceptance,
        "safety": {"blocked_invoices_marked_payment_ready": blocked_but_ready,
                   "gate": "PASS" if blocked_but_ready == 0 else "FAIL"},
        "extraction_field_accuracy": extraction,
        "exception_detection": per_code,
        "primary_exception_accuracy": round(sum(v for (a, b), v in confusion.items() if a == b) / n, 4),
        "confusion_primary": [{"expected": a, "predicted": b, "count": v} for (a, b), v in sorted(confusion.items())],
        "duplicates": {"labelled": len(dup_gt), "pairs_correct": dup_pairs_correct, "false_positives": dup_false_pos},
        "kpis": kpis,
    }
    write_json(out_dir / "metrics.json", metrics)
    return metrics
