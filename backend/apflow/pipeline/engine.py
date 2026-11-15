"""Decision engine: duplicate gate -> header validation -> three-way match ->
exception routing -> approval -> payment readiness.

Inputs are ONLY the master data (vendors, POs, receipts) and the raw
documents. Ground truth and the structured invoice tables are never read here.

Every check that fails produces an Exception record with expected vs actual
values and a plain-English message, so an analyst can see *why* an invoice
was blocked without reading code.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from apflow.config import Policy
from apflow.money import D, line_tax, q2
from apflow.pipeline.extraction import ExtractedInvoice, ExtractionError, extract, normalise_invoice_number
from apflow.policy import BLOCKED_STATES, EXCEPTIONS, match_status_for, primary_exception, queue_for


@dataclass
class Issue:
    code: str
    message: str
    line_ref: str = ""
    expected: str = ""
    actual: str = ""
    value_at_risk: Decimal = Decimal("0.00")


@dataclass
class Decision:
    invoice_id: str
    document_id: str
    received_date: date
    layout: str = ""
    vendor_id: str = ""
    po_id: str = ""
    vendor_invoice_number: str = ""
    invoice_date: date | None = None
    stated_total: Decimal = Decimal("0.00")
    computed_total: Decimal = Decimal("0.00")
    issues: list = field(default_factory=list)
    duplicate_of: str = ""
    approval_tier: int | None = None
    approval_roles: list = field(default_factory=list)
    final_state: str = ""
    payment_ready: bool = False
    due_date: date | None = None
    scheduled_payment_date: date | None = None
    payment_method: str = ""
    extracted: ExtractedInvoice | None = None
    events: list = field(default_factory=list)
    allocations: list = field(default_factory=list)
    approvals: list = field(default_factory=list)

    @property
    def codes(self):
        return sorted({i.code for i in self.issues})

    @property
    def non_po(self):
        return not self.po_id

    @property
    def primary(self):
        return primary_exception(self.codes)

    @property
    def match_status(self):
        return match_status_for(self.codes, self.non_po)

    @property
    def route_queue(self):
        return queue_for(self.codes)

    def explanation(self) -> str:
        if not self.issues:
            roles = " -> ".join(self.approval_roles)
            return f"Clean {'non-PO' if self.non_po else '3-way match'}; approved by {roles}; payment-ready."
        return " | ".join(f"{i.code}: {i.message}" for i in sorted(self.issues, key=lambda x: x.code))


class PaymentSafetyError(AssertionError):
    """Raised if code ever tries to mark a blocked invoice payment-ready."""


class Context:
    """Indexed master data + mutable running state (billed quantities, duplicate registry)."""

    def __init__(self, tables: dict, policy: Policy):
        self.p = policy
        self.vendors = {v["vendor_id"]: v for v in tables["vendors"]}
        self.vendor_by_tax = {v["tax_id"]: v for v in tables["vendors"]}
        self.vendor_by_name = {v["vendor_name"].upper(): v for v in tables["vendors"]}
        self.pos = {p["po_id"]: p for p in tables["purchase_orders"]}
        self.po_lines_by_po = {}
        for ln in tables["purchase_order_lines"]:
            self.po_lines_by_po.setdefault(ln["po_id"], {})[ln["sku"]] = ln
        grn_date = {g["grn_id"]: g["receipt_date"] for g in tables["goods_receipts"]}
        self.grn_lines_by_po_line = {}
        for gl in tables["goods_receipt_lines"]:
            self.grn_lines_by_po_line.setdefault(gl["po_line_id"], []).append(
                {"grn_line_id": gl["grn_line_id"], "qty": int(gl["quantity_received"]),
                 "date": grn_date[gl["grn_id"]]})
        for lst in self.grn_lines_by_po_line.values():
            lst.sort(key=lambda x: (x["date"], x["grn_line_id"]))     # FIFO allocation
        self.received = {k: sum(x["qty"] for x in v) for k, v in self.grn_lines_by_po_line.items()}
        self.billed = {}            # po_line_id -> quantity already invoiced (non-duplicates)
        self.allocated = {}         # grn_line_id -> quantity already matched
        self.seen = {}              # (vendor_id, normalised number) -> first invoice snapshot


class DecisionEngine:
    def __init__(self, ctx: Context, policy: Policy):
        self.ctx, self.p = ctx, policy

    # ------------------------------------------------------------ public --
    def process(self, doc: dict) -> Decision:
        d = Decision(invoice_id=doc["invoice_id"], document_id=doc["document_id"],
                     received_date=date.fromisoformat(doc["received_date"]))
        self._event(d, None, "RECEIVED", "SYSTEM", f"channel={doc['channel']}")
        try:
            ext = extract(doc["content"])
        except ExtractionError as exc:
            d.issues.append(Issue("EXTRACTION_FAILED", str(exc)))
            return self._route(d, "RECEIVED")
        d.extracted, d.layout = ext, ext.layout
        d.vendor_invoice_number, d.invoice_date = ext.vendor_invoice_number, ext.invoice_date
        d.po_id, d.stated_total = ext.po_number or "", ext.stated_total
        self._event(d, "RECEIVED", "EXTRACTED", "SYSTEM", f"layout={ext.layout}; lines={len(ext.lines)}")

        vendor = self._resolve_vendor(d, ext)
        if vendor and self._duplicate_gate(d, ext, vendor):
            self._event(d, "EXTRACTED", "DUPLICATE_BLOCKED", "SYSTEM", d.issues[0].message)
            d.final_state = "DUPLICATE_BLOCKED"
            return d
        self._event(d, "EXTRACTED", "VALIDATED", "SYSTEM", "header checks run")
        if vendor:
            self._check_vendor_status(d, ext, vendor)
        self._check_arithmetic(d, ext)
        if ext.po_number:
            self._three_way_match(d, ext, vendor)
        else:
            self._check_non_po_allowed(d, ext)
        if d.issues:
            return self._route(d, "VALIDATED")
        return self._approve_and_release(d, vendor)

    # ------------------------------------------------------------ steps ---
    def _resolve_vendor(self, d, ext):
        v = self.ctx.vendor_by_tax.get(ext.vendor_tax_id) or self.ctx.vendor_by_name.get(ext.vendor_name.upper())
        if not v:
            d.issues.append(Issue("VENDOR_UNKNOWN", f"tax ID {ext.vendor_tax_id} not in vendor master",
                                  actual=ext.vendor_tax_id))
            return None
        d.vendor_id = v["vendor_id"]
        return v

    def _signature(self, ext):
        return (ext.invoice_date, ext.stated_total,
                tuple((ln.sku, ln.quantity, ln.unit_price) for ln in ext.lines))

    def _duplicate_gate(self, d, ext, vendor) -> bool:
        key = (vendor["vendor_id"], normalise_invoice_number(ext.vendor_invoice_number))
        prior = self.ctx.seen.get(key)
        if prior is None:
            self.ctx.seen[key] = {"invoice_id": d.invoice_id, "sig": self._signature(ext),
                                  "number": ext.vendor_invoice_number}
            return False
        d.duplicate_of = prior["invoice_id"]
        if prior["sig"] == self._signature(ext):
            d.issues.append(Issue("DUPLICATE_EXACT",
                                  f"same number/date/amount as {prior['invoice_id']} ({prior['number']})",
                                  expected="unique", actual=prior["invoice_id"], value_at_risk=ext.stated_total))
        else:
            d.issues.append(Issue("DUPLICATE_NUMBER",
                                  f"number {ext.vendor_invoice_number} already used by {prior['invoice_id']} "
                                  f"with different content", expected="unique", actual=prior["invoice_id"],
                                  value_at_risk=ext.stated_total))
        return True

    def _check_vendor_status(self, d, ext, vendor):
        closed = vendor["closed_date"]
        if vendor["status"] != "ACTIVE" and (not closed or ext.invoice_date > date.fromisoformat(closed)):
            d.issues.append(Issue("VENDOR_INACTIVE", f"vendor {vendor['vendor_id']} closed on {closed}; "
                                  f"invoice dated {ext.invoice_date}", expected=f"<= {closed}",
                                  actual=str(ext.invoice_date), value_at_risk=ext.stated_total))

    def _check_arithmetic(self, d, ext):
        tol = self.p.amount_tolerance
        computed_sub, computed_tax = Decimal("0"), Decimal("0")
        for ln in ext.lines:
            amount = q2(ln.quantity * ln.unit_price)
            if abs(amount - ln.line_amount) > tol:
                d.issues.append(Issue("TOTAL_MISMATCH", f"line {ln.line_number} amount {ln.line_amount} != "
                                      f"{ln.quantity} x {ln.unit_price}", line_ref=ln.sku,
                                      expected=str(amount), actual=str(ln.line_amount)))
            computed_sub += amount
            rate = self.p.tax_rates.get(ln.tax_code)
            if rate is None:
                d.issues.append(Issue("TAX_MISMATCH", f"unknown tax code {ln.tax_code}", line_ref=ln.sku,
                                      actual=ln.tax_code))
            else:
                computed_tax += line_tax(amount, rate)
        d.computed_total = computed_sub + computed_tax
        if abs(ext.subtotal - computed_sub) > tol:
            d.issues.append(Issue("TOTAL_MISMATCH", f"subtotal {ext.subtotal} != sum of lines {computed_sub}",
                                  expected=str(computed_sub), actual=str(ext.subtotal)))
        if abs(ext.stated_total - (ext.subtotal + ext.tax_total)) > tol:
            diff = ext.stated_total - (ext.subtotal + ext.tax_total)
            d.issues.append(Issue("TOTAL_MISMATCH", f"total {ext.stated_total} != subtotal + tax "
                                  f"{ext.subtotal + ext.tax_total} (diff {diff})",
                                  expected=str(ext.subtotal + ext.tax_total), actual=str(ext.stated_total),
                                  value_at_risk=max(diff, Decimal("0"))))
        if abs(ext.tax_total - computed_tax) > tol:
            d.issues.append(Issue("TAX_MISMATCH", f"stated tax {ext.tax_total} != tax by code {computed_tax}",
                                  expected=str(computed_tax), actual=str(ext.tax_total),
                                  value_at_risk=max(ext.tax_total - computed_tax, Decimal("0"))))

    def _check_non_po_allowed(self, d, ext):
        """Only services may be billed without a PO. A goods invoice with a blank/unreadable PO
        must not skip the 3-way match (found by the robustness test)."""
        goods = [ln.sku for ln in ext.lines if not ln.sku.startswith(self.p.non_po_sku_prefixes)]
        if goods:
            d.issues.append(Issue("PO_REQUIRED", f"no PO reference but goods items billed ({goods[0]}...)",
                                  expected="PO number", actual="none", value_at_risk=ext.stated_total))

    def _three_way_match(self, d, ext, vendor):
        ctx, tol = self.ctx, self.p.price_tolerance_pct
        po = ctx.pos.get(ext.po_number)
        if not po:
            d.issues.append(Issue("PO_NOT_FOUND", f"PO {ext.po_number} does not exist", actual=ext.po_number))
            return
        if vendor and po["vendor_id"] != vendor["vendor_id"]:
            d.issues.append(Issue("VENDOR_PO_MISMATCH", f"PO {po['po_id']} belongs to {po['vendor_id']}",
                                  expected=po["vendor_id"], actual=vendor["vendor_id"]))
        if ext.invoice_date < date.fromisoformat(po["po_date"]):
            d.issues.append(Issue("DATE_BEFORE_PO", f"invoice dated {ext.invoice_date} before PO date "
                                  f"{po['po_date']}", expected=f">= {po['po_date']}", actual=str(ext.invoice_date)))
        po_lines = ctx.po_lines_by_po.get(po["po_id"], {})
        for ln in ext.lines:
            pl = po_lines.get(ln.sku)
            if not pl:
                d.issues.append(Issue("LINE_NOT_ON_PO", f"{ln.sku} not on {po['po_id']}", line_ref=ln.sku))
                continue
            plid = pl["po_line_id"]
            po_price, ordered = D(pl["unit_price"]), int(pl["quantity_ordered"])
            if ln.tax_code != pl["tax_code"]:
                d.issues.append(Issue("TAX_MISMATCH", f"{plid}: tax code {ln.tax_code} vs PO {pl['tax_code']}",
                                      line_ref=plid, expected=pl["tax_code"], actual=ln.tax_code))
            if ln.unit_price - po_price > po_price * tol:
                pct = (ln.unit_price / po_price - 1) * 100
                d.issues.append(Issue("PRICE_VARIANCE", f"{plid}: unit price {ln.unit_price} vs PO {po_price} "
                                      f"(+{pct:.2f}%, tolerance {tol * 100:.2f}%)", line_ref=plid,
                                      expected=f"<= {q2(po_price * (1 + tol))}", actual=str(ln.unit_price),
                                      value_at_risk=q2((ln.unit_price - po_price) * ln.quantity)))
            cumulative = ctx.billed.get(plid, 0) + ln.quantity
            received = ctx.received.get(plid, 0)
            if cumulative > ordered + self.p.raw["tolerances"]["quantity_units"]:
                d.issues.append(Issue("QTY_EXCEEDS_PO", f"{plid}: billed {cumulative} (cumulative) > ordered "
                                      f"{ordered}", line_ref=plid, expected=f"<= {ordered}", actual=str(cumulative),
                                      value_at_risk=q2((cumulative - ordered) * ln.unit_price)))
            if received == 0:
                d.issues.append(Issue("MISSING_RECEIPT", f"{plid}: no goods receipt posted", line_ref=plid,
                                      expected="> 0 received", actual="0",
                                      value_at_risk=ln.line_amount))
            elif cumulative > received:
                d.issues.append(Issue("QTY_EXCEEDS_RECEIVED", f"{plid}: billed {cumulative} (cumulative) > "
                                      f"received {received}", line_ref=plid, expected=f"<= {received}",
                                      actual=str(cumulative),
                                      value_at_risk=q2((cumulative - received) * ln.unit_price)))
            ctx.billed[plid] = cumulative
            self._allocate(d, ln, plid)

    def _allocate(self, d, ln, plid):
        """FIFO-allocate billed quantity to receipt lines -> invoice<->receipt bridge (N:M)."""
        remaining = ln.quantity
        for gl in self.ctx.grn_lines_by_po_line.get(plid, []):
            free = gl["qty"] - self.ctx.allocated.get(gl["grn_line_id"], 0)
            if free <= 0 or remaining <= 0:
                continue
            take = min(free, remaining)
            self.ctx.allocated[gl["grn_line_id"]] = self.ctx.allocated.get(gl["grn_line_id"], 0) + take
            remaining -= take
            d.allocations.append({"invoice_id": d.invoice_id, "invoice_line_number": ln.line_number,
                                  "po_line_id": plid, "grn_line_id": gl["grn_line_id"], "quantity": take})

    # ------------------------------------------------------------ outcomes --
    def _route(self, d, from_state):
        queue = d.route_queue
        self._event(d, from_state, "EXCEPTION_ROUTED", "SYSTEM",
                    f"primary={d.primary}; queue={queue}; codes={'|'.join(d.codes)}")
        d.final_state = "EXCEPTION_ROUTED"
        return d

    def _approve_and_release(self, d, vendor):
        total = d.stated_total
        tier = self.p.approval_tier(total, d.non_po)
        d.approval_tier, d.approval_roles = tier["tier"], list(tier["roles"])
        self._event(d, "VALIDATED", "MATCHED", "SYSTEM",
                    "non-PO: header and tax checks passed" if d.non_po else "3-way match within tolerance")
        self._event(d, "MATCHED", "APPROVAL_PENDING", "SYSTEM", f"tier {tier['tier']}: {'|'.join(tier['roles'])}")
        when = d.received_date
        state = "APPROVAL_PENDING"
        for level, role in enumerate(d.approval_roles, 1):
            # Human approvals are simulated (decision = APPROVED) so the flow can be measured end to end.
            when = min(self.p.as_of, when + timedelta(days=0 if role == "SYSTEM_AUTO" else 1))
            d.approvals.append({"invoice_id": d.invoice_id, "level": level, "approver_role": role,
                                "decision": "APPROVED", "decided_date": when, "simulated": role != "SYSTEM_AUTO"})
            self._event(d, state, "APPROVED", role, f"level {level} approved")
            state = "APPROVED"
        self._mark_payment_ready(d)
        terms = int(vendor["payment_terms_days"])
        d.due_date = d.invoice_date + timedelta(days=terms)
        d.scheduled_payment_date = max(d.due_date, when)
        d.payment_method = vendor["payment_method"]
        self._event(d, "APPROVED", "PAYMENT_READY", "SYSTEM", f"scheduled {d.scheduled_payment_date}")
        d.final_state = "PAYMENT_READY"
        return d

    @staticmethod
    def _mark_payment_ready(d):
        """Hard control: a blocked or unapproved invoice can never be released."""
        if d.issues or d.final_state in BLOCKED_STATES or len(d.approvals) != len(d.approval_roles) \
                or not d.approval_roles:
            raise PaymentSafetyError(f"{d.invoice_id} is not eligible for payment")
        d.payment_ready = True

    def _event(self, d, from_state, to_state, actor, reason):
        seq = len(d.events) + 1
        d.events.append({"invoice_id": d.invoice_id, "sequence": seq,
                         "event_time": f"{d.received_date.isoformat()}T09:{seq:02d}:00",
                         "from_state": from_state or "", "to_state": to_state, "actor": actor, "reason": reason})


def severity(code: str) -> str:
    return EXCEPTIONS[code][0]
