"""Dataset validation (Step 8): keys, joins, enums, dates, arithmetic,
lifecycle, duplicates, labels and volumes.

Each check returns PASS/FAIL with a failure count and up to 5 examples, so a
reviewer can see exactly what was verified. Deliberate anomalies are only
accepted when the ground truth labels them.
"""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from apflow.config import Policy, allocate
from apflow.export import load_dataset, write_json
from apflow.money import D, line_tax, q2
from apflow.pipeline.extraction import normalise_invoice_number
from apflow.policy import PO_TRANSITIONS
from apflow.schema import ALL_TABLES, TABLES


class Report:
    def __init__(self):
        self.checks = []

    def add(self, category, name, failures, total=None):
        self.checks.append({"category": category, "check": name, "status": "PASS" if not failures else "FAIL",
                            "failures": len(failures), "checked": total, "examples": [str(f) for f in failures[:5]]})

    @property
    def passed(self):
        return all(c["status"] == "PASS" for c in self.checks)

    def summary(self):
        return {"passed": self.passed, "checks_total": len(self.checks),
                "checks_failed": sum(c["status"] == "FAIL" for c in self.checks), "checks": self.checks}


def _type_ok(ftype, value):
    try:
        if ftype == "integer":
            int(value)
        elif ftype == "decimal":
            Decimal(value)
        elif ftype == "date":
            date.fromisoformat(value)
        return True
    except (ValueError, InvalidOperation):
        return False


def validate_schema(data, rep: Report):
    for t in ALL_TABLES:
        rows = data[t.name]
        req, typ, enum, pat, uniq = [], [], [], [], []
        for f in t.fields:
            rx = re.compile(f.pattern) if f.pattern else None
            seen = {}
            for i, r in enumerate(rows):
                v = r.get(f.name, "")
                if v == "":
                    if f.required:
                        req.append(f"{t.name}[{i}].{f.name} empty")
                    continue
                if not _type_ok(f.type, v):
                    typ.append(f"{t.name}[{i}].{f.name}={v!r} not {f.type}")
                if f.allowed and v not in [str(a) for a in f.allowed]:
                    enum.append(f"{t.name}[{i}].{f.name}={v!r}")
                if rx and not rx.match(v):
                    pat.append(f"{t.name}[{i}].{f.name}={v!r}")
                if f.unique or f.name == t.pk:
                    if v in seen:
                        uniq.append(f"{t.name}.{f.name} duplicate {v}")
                    seen[v] = i
        rep.add("schema", f"{t.name}: required fields present", req, len(rows))
        rep.add("schema", f"{t.name}: data types parse", typ, len(rows))
        rep.add("enums", f"{t.name}: allowed values", enum, len(rows))
        rep.add("ids", f"{t.name}: ID/format patterns", pat, len(rows))
        rep.add("keys", f"{t.name}: primary key + unique fields", uniq, len(rows))


def validate_foreign_keys(data, rep: Report):
    for t in ALL_TABLES:
        for f in t.fields:
            if not f.fk:
                continue
            ref_t, ref_c = f.fk.split(".")
            keys = {r[ref_c] for r in data[ref_t]}
            bad = [f"{t.name}.{f.name}={r[f.name]}" for r in data[t.name] if r[f.name] and r[f.name] not in keys]
            rep.add("foreign_keys", f"{t.name}.{f.name} -> {f.fk}", bad, len(data[t.name]))


def validate_business(data, p: Policy, rep: Report):
    vendors = {v["vendor_id"]: v for v in data["vendors"]}
    pos = {x["po_id"]: x for x in data["purchase_orders"]}
    po_lines = {x["po_line_id"]: x for x in data["purchase_order_lines"]}
    grns = {g["grn_id"]: g for g in data["goods_receipts"]}
    invoices = {i["invoice_id"]: i for i in data["invoices"]}
    gt = {g["invoice_id"]: g for g in data["ground_truth"]}
    as_of = p.as_of
    lines_by_po, lines_by_inv, grnl_by_grn = {}, {}, {}
    for ln in data["purchase_order_lines"]:
        lines_by_po.setdefault(ln["po_id"], []).append(ln)
    for ln in data["invoice_lines"]:
        lines_by_inv.setdefault(ln["invoice_id"], []).append(ln)
    for gl in data["goods_receipt_lines"]:
        grnl_by_grn.setdefault(gl["grn_id"], []).append(gl)

    def labelled(inv_id, code):
        return code in gt.get(inv_id, {}).get("expected_exceptions", "").split("|")

    # --- volumes & mix
    vol = p.volumes
    actual = {"vendors": len(vendors), "purchase_orders": len(pos), "purchase_order_lines": len(po_lines),
              "goods_receipts": len(grns), "invoices": len(invoices)}
    rep.add("volume", "row counts equal configured volumes",
            [f"{k}: {actual[k]} != {vol[k]}" for k in actual if actual[k] != vol[k]])
    target = allocate(vol["invoices"], p.scenario_mix)
    got = {}
    for g in gt.values():
        got[g["scenario"]] = got.get(g["scenario"], 0) + 1
    rep.add("volume", "scenario mix equals target allocation",
            [f"{k}: {got.get(k, 0)} != {v}" for k, v in target.items() if got.get(k, 0) != v])

    # --- structure
    bad = [f"{pid} has {len(ls)} lines" for pid, ls in lines_by_po.items() if not 1 <= len(ls) <= 8]
    bad += [f"{pid} missing lines" for pid in pos if pid not in lines_by_po]
    rep.add("structure", "every PO has 1-8 lines", bad, len(pos))
    bad = []
    for pid, ls in lines_by_po.items():
        if len({x["sku"] for x in ls}) != len(ls):
            bad.append(f"{pid} repeats a SKU")
        if sorted(int(x["line_number"]) for x in ls) != list(range(1, len(ls) + 1)):
            bad.append(f"{pid} line numbers not 1..n")
    rep.add("structure", "PO line numbers contiguous and SKUs unique per PO", bad, len(pos))
    bad = [gl["grn_line_id"] for gl in data["goods_receipt_lines"]
           if po_lines[gl["po_line_id"]]["po_id"] != grns[gl["grn_id"]]["po_id"]]
    bad += [g["grn_id"] for g in grns.values() if g["vendor_id"] != pos[g["po_id"]]["vendor_id"]]
    rep.add("joins", "receipt lines belong to the receipt's PO and vendor", bad, len(data["goods_receipt_lines"]))
    bad = [ln["invoice_line_id"] for ln in data["invoice_lines"] if ln["po_line_id"]
           and po_lines[ln["po_line_id"]]["po_id"] != invoices[ln["invoice_id"]]["po_id"]]
    bad += [i["invoice_id"] for i in invoices.values() if i["po_id"] and pos[i["po_id"]]["vendor_id"] != i["vendor_id"]]
    rep.add("joins", "invoice lines reference PO lines of the invoice's PO; PO vendor = invoice vendor", bad)
    bad = [i["invoice_id"] for i in invoices.values()
           if not i["invoice_id"].startswith(f"INV-{vendors[i['vendor_id']]['vendor_code']}-")]
    bad += [ln["invoice_line_id"] for ln in data["invoice_lines"]
            if not ln["invoice_line_id"].startswith(f"INVL-{ln['invoice_id']}-")]
    rep.add("ids", "invoice IDs embed vendor code; line IDs embed invoice ID", bad)

    # --- arithmetic (derived values recomputed from source)
    bad = []
    for ln in po_lines.values():
        amt = q2(int(ln["quantity_ordered"]) * D(ln["unit_price"]))
        if amt != D(ln["line_amount"]) or line_tax(amt, p.tax_rates[ln["tax_code"]]) != D(ln["line_tax_amount"]):
            bad.append(ln["po_line_id"])
    for pid, po in pos.items():
        ls = lines_by_po.get(pid, [])
        sub = sum((D(x["line_amount"]) for x in ls), Decimal("0"))
        tax = sum((D(x["line_tax_amount"]) for x in ls), Decimal("0"))
        if (D(po["subtotal_amount"]), D(po["tax_amount"]), D(po["total_amount"]), int(po["line_count"])) != \
                (sub, tax, sub + tax, len(ls)):
            bad.append(pid)
    rep.add("arithmetic", "PO line and header totals reconcile", bad, len(pos))
    bad = []
    for iid, inv in invoices.items():
        ls = lines_by_inv[iid]
        for ln in ls:
            amt = q2(int(ln["quantity"]) * D(ln["unit_price"]))
            if amt != D(ln["line_amount"]):
                bad.append(ln["invoice_line_id"])
            if line_tax(amt, p.tax_rates[ln["tax_code"]]) != D(ln["line_tax_amount"]) and \
                    not labelled(iid, "TAX_MISMATCH"):
                bad.append(f"{ln['invoice_line_id']} tax (unlabelled)")
        sub = sum((D(x["line_amount"]) for x in ls), Decimal("0"))
        tax = sum((D(x["line_tax_amount"]) for x in ls), Decimal("0"))
        if D(inv["subtotal_amount"]) != sub or D(inv["tax_amount"]) != tax or int(inv["line_count"]) != len(ls):
            bad.append(f"{iid} subtotal/tax")
        if D(inv["total_amount"]) != sub + tax and not labelled(iid, "TOTAL_MISMATCH"):
            bad.append(f"{iid} total (unlabelled)")
    rep.add("arithmetic", "invoice line, tax and grand totals reconcile (except labelled defects)", bad, len(invoices))
    bad = []
    for iid, inv in invoices.items():
        if labelled(iid, "TOTAL_MISMATCH") and D(inv["total_amount"]) == D(inv["subtotal_amount"]) + D(inv["tax_amount"]):
            bad.append(iid)
    rep.add("labels", "every TOTAL_MISMATCH label is a real mismatch", bad)

    # --- receipts derived on PO lines + PO status
    recv = {}
    for gl in data["goods_receipt_lines"]:
        recv[gl["po_line_id"]] = recv.get(gl["po_line_id"], 0) + int(gl["quantity_received"])
    bad = []
    for plid, ln in po_lines.items():
        r, q = recv.get(plid, 0), int(ln["quantity_ordered"])
        status = "NOT_RECEIVED" if r == 0 else "PARTIAL" if r < q else "FULL" if r == q else "OVER"
        if int(ln["quantity_received"]) != r or ln["receipt_status"] != status:
            bad.append(plid)
    for pid, po in pos.items():
        ls = lines_by_po[pid]
        if all(recv.get(x["po_line_id"], 0) == 0 for x in ls):
            st = "CREATED"
        elif all(recv.get(x["po_line_id"], 0) >= int(x["quantity_ordered"]) for x in ls):
            st = "RECEIVED"
        else:
            st = "PARTIALLY_RECEIVED"
        if po["status"] != st:
            bad.append(f"{pid} status {po['status']} != {st}")
    rep.add("derived", "received quantities, receipt status and PO status derived from GRNs", bad, len(po_lines))

    # --- lifecycle
    ev_by_po = {}
    for e in data["purchase_order_events"]:
        ev_by_po.setdefault(e["po_id"], []).append(e)
    bad = []
    for pid, po in pos.items():
        evs = sorted(ev_by_po.get(pid, []), key=lambda e: int(e["sequence"]))
        prev, prev_date = None, None
        for e in evs:
            if (e["from_status"] or None) != prev or e["to_status"] not in PO_TRANSITIONS[prev]:
                bad.append(f"{pid}: {prev} -> {e['to_status']}")
            if prev_date and e["event_date"] < prev_date:
                bad.append(f"{pid}: event dates go backwards")
            prev, prev_date = e["to_status"], e["event_date"]
        if prev != po["status"]:
            bad.append(f"{pid}: last event {prev} != status {po['status']}")
    rep.add("lifecycle", "PO event history follows allowed transitions and ends at current status", bad, len(pos))

    # --- dates
    bad = []
    for pid, po in pos.items():
        v = vendors[po["vendor_id"]]
        if po["po_date"] < v["onboarded_date"]:
            bad.append(f"{pid} before vendor onboarding")
        if v["closed_date"] and po["po_date"] >= v["closed_date"]:
            bad.append(f"{pid} on/after vendor closure")
    for g in grns.values():
        if not pos[g["po_id"]]["po_date"] <= g["receipt_date"] <= as_of.isoformat():
            bad.append(f"{g['grn_id']} receipt date out of order")
    for iid, inv in invoices.items():
        if not inv["invoice_date"] <= inv["received_date"] <= as_of.isoformat():
            bad.append(f"{iid} received/invoice date order")
        if inv["po_id"] and inv["invoice_date"] < pos[inv["po_id"]]["po_date"] and not labelled(iid, "DATE_BEFORE_PO"):
            bad.append(f"{iid} before PO (unlabelled)")
        v = vendors[inv["vendor_id"]]
        if v["closed_date"] and inv["invoice_date"] > v["closed_date"] and not labelled(iid, "VENDOR_INACTIVE"):
            bad.append(f"{iid} after vendor closure (unlabelled)")
    for v in vendors.values():
        if (v["status"] == "CLOSED") != bool(v["closed_date"]) or (v["closed_date"] and v["closed_date"] <= v["onboarded_date"]):
            bad.append(f"{v['vendor_id']} closed status/date inconsistent")
    rep.add("dates", "date ordering: onboarding <= PO <= receipt; invoice <= received <= as-of; closures", bad)

    # --- duplicates only where labelled, and labels point to the right pair
    first, bad = {}, []
    for inv in sorted(invoices.values(), key=lambda i: (i["received_date"], i["invoice_id"][-6:])):
        key = (inv["vendor_id"], normalise_invoice_number(inv["vendor_invoice_number"]))
        g = gt[inv["invoice_id"]]
        if key in first:
            if g["scenario"] != "duplicate" or g["duplicate_of_invoice_id"] != first[key]:
                bad.append(f"{inv['invoice_id']} duplicates {first[key]} but label says {g['duplicate_of_invoice_id']!r}")
        else:
            first[key] = inv["invoice_id"]
            if g["scenario"] == "duplicate":
                bad.append(f"{inv['invoice_id']} labelled duplicate but number is first occurrence")
    rep.add("duplicates", "duplicate vendor invoice numbers exist only as labelled pairs", bad, len(invoices))

    # --- ground truth separation and coverage
    bad = [i for i in invoices if i not in gt] + [g for g in gt if g not in invoices]
    rep.add("ground_truth", "one ground-truth row per invoice", bad)
    leak = []
    for t in ALL_TABLES:
        if t.group != "ground_truth":
            leak += [f"{t.name}.{c}" for c in t.columns if c.startswith("expected_") or c in ("scenario", "issue_type")]
    rep.add("ground_truth", "no label columns in input/reference tables", leak)

    # --- approvals and payments only for eligible invoices
    appr_by_inv = {}
    for a in data["approvals"]:
        appr_by_inv.setdefault(a["invoice_id"], []).append(a)
    bad = []
    for iid, g in gt.items():
        eligible = g["expected_payment_ready"] == "true"
        roles = "|".join(a["approver_role"] for a in sorted(appr_by_inv.get(iid, []), key=lambda a: int(a["level"])))
        if eligible and roles != g["expected_approval_roles"]:
            bad.append(f"{iid} approvals {roles!r} != policy {g['expected_approval_roles']!r}")
        if not eligible and iid in appr_by_inv:
            bad.append(f"{iid} approved but not eligible")
        if eligible and g["expected_exceptions"]:
            bad.append(f"{iid} eligible with exceptions")
    for a in data["approvals"]:
        if a["decided_date"] < invoices[a["invoice_id"]]["received_date"]:
            bad.append(f"{a['approval_id']} decided before receipt")
    rep.add("policy", "approvals exist only for eligible invoices and match the approval matrix", bad, len(gt))
    bad = []
    for pay in data["payments"]:
        iid = pay["invoice_id"]
        inv = invoices[iid]
        if gt[iid]["expected_payment_ready"] != "true" or iid not in appr_by_inv:
            bad.append(f"{pay['payment_id']} for blocked/unapproved invoice {iid}")
        if D(pay["amount"]) != D(inv["total_amount"]):
            bad.append(f"{pay['payment_id']} amount != invoice total")
        due = date.fromisoformat(inv["invoice_date"]) + timedelta(days=int(vendors[inv["vendor_id"]]["payment_terms_days"]))
        if pay["due_date"] != due.isoformat():
            bad.append(f"{pay['payment_id']} due date")
        last_appr = max(a["decided_date"] for a in appr_by_inv.get(iid, [{"decided_date": "9999"}]))
        if pay["scheduled_date"] < last_appr:
            bad.append(f"{pay['payment_id']} scheduled before approval")
        if (pay["status"] == "PAID") != (pay["scheduled_date"] <= as_of.isoformat()) or \
                (pay["status"] == "PAID") != bool(pay["paid_date"]):
            bad.append(f"{pay['payment_id']} status/paid_date")
    eligible_n = sum(g["expected_payment_ready"] == "true" for g in gt.values())
    if len(data["payments"]) != eligible_n:
        bad.append(f"{len(data['payments'])} payments for {eligible_n} eligible invoices")
    rep.add("policy", "payments only for approved eligible invoices; amounts/dates derived", bad, len(data["payments"]))

    # --- documents
    docs = {d["invoice_id"]: d for d in data["_documents"]}
    bad = [i for i in invoices if i not in docs or docs[i]["document_id"] != invoices[i]["document_id"]]
    rep.add("joins", "every invoice has exactly one raw document", bad, len(invoices))


def validate(data_dir, policy: Policy) -> dict:
    data = load_dataset(data_dir)
    rep = Report()
    validate_schema(data, rep)
    validate_foreign_keys(data, rep)
    try:
        validate_business(data, policy, rep)
    except (KeyError, ValueError, InvalidOperation) as exc:
        # broken keys/values upstream (already reported above) can stop rule checks from running
        rep.add("business", "business rules could be evaluated", [f"{type(exc).__name__}: {exc}"])
    summary = rep.summary()
    write_json(Path(data_dir) / "validation_summary.json", summary)
    lines = ["# Validation Summary", "", f"Overall: **{'PASS' if summary['passed'] else 'FAIL'}** "
             f"({summary['checks_total'] - summary['checks_failed']}/{summary['checks_total']} checks passed)", "",
             "| Category | Check | Status | Failures |", "|---|---|---|---|"]
    for c in summary["checks"]:
        lines.append(f"| {c['category']} | {c['check']} | {c['status']} | {c['failures']} |")
    (Path(data_dir) / "validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return summary


__all__ = ["validate", "TABLES"]
