"""Deterministic synthetic AP dataset generator.

Order of work (parents before children, labels derived from rules):
    1. vendors                      (master)
    2. purchase orders + lines      (master, 1-8 lines each)
    3. billing plan                 (which PO lines each invoice will bill + its scenario)
    4. goods receipts + lines       (full / partial / over-receipt / none, driven by the plan)
    5. invoices + lines             (valid baseline first, then labelled anomalies)
    6. duplicates, closed vendors, non-PO invoices
    7. intake order -> immutable IDs, raw documents
    8. ground truth, approvals and payments derived from the rule table

Every random choice comes from one `random.Random(seed)`, and nothing iterates
over an unordered set, so the same seed always produces byte-identical files.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from apflow import ids
from apflow.config import Policy, allocate
from apflow.generator import catalog as cat
from apflow.generator.documents import render
from apflow.money import D, line_tax, q2
from apflow.policy import EXPECTED_EXCEPTIONS, match_status_for, primary_exception, queue_for


class GenerationError(RuntimeError):
    pass


class Generator:
    def __init__(self, policy: Policy):
        self.p = policy
        self.rng = random.Random(policy.seed)
        self.year = policy.fiscal_year
        self.as_of = policy.as_of

    # ------------------------------------------------------------ helpers --
    def _date_between(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rng.randint(0, max(0, (end - start).days)))

    def _cap(self, d: date, floor: date | None = None, margin: int = 0) -> date:
        cap = self.as_of - timedelta(days=margin)
        d = min(d, cap)
        return max(d, floor) if floor else d

    # ------------------------------------------------------------ 1 vendors --
    def make_vendors(self):
        rng, n = self.rng, self.p.volumes["vendors"]
        names, seen = [], set()
        while len(names) < n:
            name = (f"{rng.choice(cat.NAME_A)} {rng.choice(cat.NAME_B)} "
                    f"{rng.choice(cat.NAME_C)} {rng.choice(cat.NAME_D)}")
            if name not in seen:
                seen.add(name)
                names.append(name)
        onboard = sorted(self._date_between(date(2018, 1, 1), date(2025, 12, 15)) for _ in range(n))

        vendors, prefix_counter, tax_ids = [], {}, set()
        for i, (name, ob) in enumerate(zip(names, onboard), 1):
            prefix = "".join(ch for ch in name.split()[0].upper() if ch.isalpha())[:3].ljust(3, "X")
            prefix_counter[prefix] = prefix_counter.get(prefix, 0) + 1
            if prefix_counter[prefix] > 99:
                raise GenerationError("vendor_code space exhausted; add more NAME_A words")
            while True:
                tax_id = f"{rng.choice(cat.UNISSUED_EIN_PREFIXES)}-{rng.randint(0, 9999999):07d}"
                if tax_id not in tax_ids:
                    tax_ids.add(tax_id)
                    break
            cats = rng.sample(cat.PO_CATEGORIES, k=rng.choice([1, 1, 2]))
            terms = rng.choices(list(cat.PAYMENT_TERMS), weights=[10, 50, 25, 15])[0]
            vendors.append({
                "vendor_id": ids.vendor_id(i),
                "vendor_code": f"{prefix}{prefix_counter[prefix]:02d}",
                "vendor_name": name,
                "tax_id": tax_id,
                "state": rng.choice(cat.US_STATES),
                "categories": "|".join(sorted(cats)),
                "payment_terms": terms,
                "payment_terms_days": cat.PAYMENT_TERMS[terms],
                "invoice_channel": rng.choices(["EMAIL", "PORTAL", "EDI"], weights=[45, 35, 20])[0],
                "payment_method": rng.choices(["ACH", "WIRE", "CHECK"], weights=[70, 20, 10])[0],
                "status": "ACTIVE",
                "onboarded_date": ob,
                "closed_date": None,
                # internal (not exported)
                "_cats": cats,
                "_factor": {c: Decimal(str(round(rng.uniform(0.92, 1.08), 4))) for c in cats},
                "_weight": rng.paretovariate(1.3),
                "_num_style": rng.randrange(3),
                "_num_start": rng.randint(1, 4000),
            })
        self.vendors = vendors
        self.vendor_by_id = {v["vendor_id"]: v for v in vendors}

    # --------------------------------------------------------- 2 POs/lines --
    def make_purchase_orders(self):
        rng, vol = self.rng, self.p.volumes
        n_po, n_lines = vol["purchase_orders"], vol["purchase_order_lines"]
        if n_lines > n_po * 8:
            raise GenerationError("too many PO lines for 8-lines-per-PO cap")
        self.catalog = cat.build_catalog(rng)
        by_cat = cat.skus_by_category(self.catalog)

        dates = sorted(self._date_between(self.p.po_start, self.p.po_end) for _ in range(n_po))
        weights = [v["_weight"] for v in self.vendors]
        counts = [1] * n_po
        for _ in range(n_lines - n_po):          # rich-get-richer -> skewed 1..8 lines
            w = [c if c < 8 else 0 for c in counts]
            counts[rng.choices(range(n_po), weights=w)[0]] += 1

        pos, lines = [], []
        for i, (po_date, k) in enumerate(zip(dates, counts), 1):
            vendor = rng.choices(self.vendors, weights=weights)[0]
            pid = ids.po_id(i, self.year)
            pool = [s for c in vendor["_cats"] for s in by_cat[c]]
            skus = rng.sample(pool, k=min(k, len(pool)))
            po = {"po_id": pid, "vendor_id": vendor["vendor_id"], "po_date": po_date,
                  "requester_id": f"REQ-{rng.randint(1, 80):04d}", "buyer_id": f"BUY-{rng.randint(1, 12):02d}",
                  "cost_center": rng.choice(cat.COST_CENTERS), "currency": self.p.currency, "_lines": []}
            for ln_no, sku in enumerate(skus, 1):
                item = self.catalog[sku]
                qlo, qhi = cat.CATEGORIES[item["category"]]["qty"]
                qty = max(1, int(round(cat.log_uniform(rng, qlo, qhi))))
                price = q2(item["base_price"] * vendor["_factor"][item["category"]])
                line = {"po_line_id": ids.po_line_id(pid, ln_no), "po_id": pid, "line_number": ln_no,
                        "sku": sku, "description": item["description"], "uom": item["uom"],
                        "quantity_ordered": qty, "unit_price": max(price, Decimal("0.01")),
                        "tax_code": item["tax_code"]}
                line["line_amount"] = q2(qty * line["unit_price"])
                line["line_tax_amount"] = line_tax(line["line_amount"], self.p.tax_rates[line["tax_code"]])
                po["_lines"].append(line)
                lines.append(line)
            pos.append(po)
        self.pos, self.po_lines = pos, lines
        self.po_by_id = {p["po_id"]: p for p in pos}
        self.line_by_id = {ln["po_line_id"]: ln for ln in lines}

    # ------------------------------------------------------- 3 billing plan --
    def plan_invoices(self):
        rng, p = self.rng, self.p
        n_inv = p.volumes["invoices"]
        self.mix = allocate(n_inv, p.scenario_mix)
        self.sub_mix = {s: allocate(self.mix[s], p.sub_scenario_mix[s]) for s in self.mix}
        n_dup = self.mix["duplicate"]
        n_nonpo = self.sub_mix["clean"]["non_po"]
        n_groups = n_inv - n_dup - n_nonpo

        # how many invoices bill each PO (split billing for multi-line POs)
        per_po = {po["po_id"]: 1 for po in self.pos}
        extra = n_groups - len(self.pos)
        if extra < 0:
            for po in rng.sample(self.pos, -extra):
                per_po[po["po_id"]] = 0          # not yet billed
        while extra > 0:
            eligible = [po for po in self.pos if per_po[po["po_id"]] < len(po["_lines"])]
            if not eligible:
                raise GenerationError("not enough PO lines to create the requested invoice volume")
            per_po[rng.choice(eligible)["po_id"]] += 1
            extra -= 1

        groups = []
        for po in self.pos:
            g = per_po[po["po_id"]]
            if g == 0:
                continue
            lines = po["_lines"]
            cuts = sorted(rng.sample(range(1, len(lines)), g - 1)) if g > 1 else []
            bounds = [0] + cuts + [len(lines)]
            for a, b in zip(bounds, bounds[1:]):
                groups.append({"po": po, "lines": lines[a:b]})
        rng.shuffle(groups)

        labels = []
        for scenario, subs in self.sub_mix.items():
            if scenario == "duplicate":
                continue
            for sub, count in subs.items():
                if sub == "non_po":
                    continue
                if sub == "exceeds_po_quantity":
                    v = allocate(count, {"received_as_ordered": 1, "over_received": 1})
                    labels += [(scenario, sub, k) for k, c in v.items() for _ in range(c)]
                elif sub == "tax_mismatch":
                    v = allocate(count, {"wrong_code": 1, "wrong_amount": 1})
                    labels += [(scenario, sub, k) for k, c in v.items() for _ in range(c)]
                else:
                    labels += [(scenario, sub, "")] * count
        assert len(labels) == len(groups), (len(labels), len(groups))

        group_count_by_vendor = {}
        for g in groups:
            vid = g["po"]["vendor_id"]
            group_count_by_vendor[vid] = group_count_by_vendor.get(vid, 0) + 1

        def has_qty2(g):
            return [ln for ln in g["lines"] if ln["quantity_ordered"] >= 2]

        def has_price20(g):
            return [ln for ln in g["lines"] if ln["unit_price"] >= 20]

        def has_amount50(g):
            return [ln for ln in g["lines"] if ln["line_amount"] >= 50]

        constraints = {
            "partial_delivery": has_qty2,
            "partial_receipt_billed_at_received": has_qty2,
            "within_tolerance_price": has_price20,
            "tax_mismatch": has_amount50,
        }
        # most constrained first
        priority = ["closed_vendor", "partial_delivery", "partial_receipt_billed_at_received",
                    "within_tolerance_price", "tax_mismatch"]
        ordered_labels = sorted(labels, key=lambda l: priority.index(l[1]) if l[1] in priority else 99)

        free = list(groups)
        closed_vendors_used = []
        for label in ordered_labels:
            scenario, sub, variant = label
            chosen, targets = None, None
            if sub == "closed_vendor":
                cands = sorted((g for g in free if g["po"]["vendor_id"] not in closed_vendors_used),
                               key=lambda g: (group_count_by_vendor[g["po"]["vendor_id"]], g["po"]["po_id"]))
                chosen = cands[0]
                closed_vendors_used.append(chosen["po"]["vendor_id"])
                targets = chosen["lines"]
            elif sub in constraints:
                for g in free:
                    t = constraints[sub](g)
                    if t:
                        chosen, targets = g, t
                        break
                if chosen is None:
                    raise GenerationError(f"no PO line satisfies constraint for {sub}")
            else:
                chosen, targets = free[0], free[0]["lines"]
            free.remove(chosen)
            chosen["scenario"], chosen["sub"], chosen["variant"] = scenario, sub, variant
            target = max(targets, key=lambda ln: ln["line_amount"]) if sub == "tax_mismatch" else rng.choice(targets)
            chosen["target"] = target
        self.groups = groups
        self.closed_vendor_ids = closed_vendors_used
        self.n_nonpo, self.n_dup = n_nonpo, n_dup

    # ----------------------------------------------------------- 4 receipts --
    def make_receipts(self):
        rng = self.rng
        received = {ln["po_line_id"]: ln["quantity_ordered"] for ln in self.po_lines}
        billed_lines = set()
        for g in self.groups:
            for ln in g["lines"]:
                billed_lines.add(ln["po_line_id"])
            t, sub = g["target"], g["sub"]
            ordered = t["quantity_ordered"]
            if sub == "no_goods_receipt":
                for ln in g["lines"]:
                    received[ln["po_line_id"]] = 0
            elif sub in ("partial_delivery", "partial_receipt_billed_at_received"):
                received[t["po_line_id"]] = max(1, min(ordered - 1, int(ordered * rng.uniform(0.3, 0.8))))
            elif sub == "over_receipt_billed_at_po":
                received[t["po_line_id"]] = ordered + max(1, int(round(ordered * rng.uniform(0.02, 0.10))))
            elif sub == "exceeds_po_quantity":
                extra = max(1, int(round(ordered * rng.uniform(0.05, 0.20))))
                g["billed_extra"] = extra
                if g["variant"] == "over_received":
                    received[t["po_line_id"]] = ordered + extra
        for ln in self.po_lines:                      # unbilled lines: open orders
            if ln["po_line_id"] not in billed_lines:
                r = rng.random()
                if r < 0.15:
                    received[ln["po_line_id"]] = 0
                elif r < 0.40 and ln["quantity_ordered"] >= 2:
                    received[ln["po_line_id"]] = rng.randint(1, ln["quantity_ordered"] - 1)

        # one shipment per PO, then split shipments until the GRN target is met
        shipments = {}
        for po in self.pos:
            ship = {ln["po_line_id"]: received[ln["po_line_id"]] for ln in po["_lines"] if received[ln["po_line_id"]] > 0}
            if ship:
                shipments[po["po_id"]] = [ship]
        extra = self.p.volumes["goods_receipts"] - len(shipments)
        if extra < 0:
            raise GenerationError("goods_receipts volume lower than POs that need a receipt")
        po_ids = list(shipments)
        def splittable(s):
            return len(s) >= 2 or max(s.values()) >= 2

        while extra > 0:
            if not po_ids:
                raise GenerationError("cannot split receipts enough to reach goods_receipts volume")
            pid = rng.choice(po_ids)
            ships = shipments[pid]
            cands = [s for s in ships if splittable(s)]
            if len(ships) >= 4 or not cands:
                po_ids.remove(pid)
                continue
            s = cands[-1]
            keys = list(s)
            if len(keys) >= 2:                     # deliver some lines later
                moved = rng.sample(keys, rng.randint(1, len(keys) - 1))
                ships.append({k: s.pop(k) for k in sorted(moved)})
            else:                                  # split one line's quantity
                k = keys[0]
                part = rng.randint(1, s[k] - 1)
                s[k] -= part
                ships.append({k: part})
            extra -= 1

        grns_tmp = []
        for pid in sorted(shipments):
            po = self.po_by_id[pid]
            d = po["po_date"]
            for idx, ship in enumerate(shipments[pid]):
                gap = rng.randint(3, 25) if idx == 0 else rng.randint(2, 15)
                d = self._cap(d + timedelta(days=gap), floor=d, margin=8)
                grns_tmp.append((d, pid, idx, ship))
        grns_tmp.sort(key=lambda x: (x[0], x[1], x[2]))

        self.grns, self.grn_lines = [], []
        self.receipt_dates_by_line = {}
        for n, (d, pid, idx, ship) in enumerate(grns_tmp, 1):
            gid = ids.grn_id(n, self.year)
            po = self.po_by_id[pid]
            self.grns.append({"grn_id": gid, "po_id": pid, "vendor_id": po["vendor_id"], "receipt_date": d,
                              "warehouse": rng.choice(cat.WAREHOUSES), "line_count": len(ship)})
            order = sorted(ship, key=lambda k: self.line_by_id[k]["line_number"])
            for ln_no, plid in enumerate(order, 1):
                self.grn_lines.append({"grn_line_id": ids.grn_line_id(gid, ln_no), "grn_id": gid,
                                       "po_line_id": plid, "quantity_received": ship[plid]})
                self.receipt_dates_by_line.setdefault(plid, []).append(d)

        # derived PO fields + append-only PO status history
        for ln in self.po_lines:
            r = received[ln["po_line_id"]]
            ln["quantity_received"] = r
            q = ln["quantity_ordered"]
            ln["receipt_status"] = "NOT_RECEIVED" if r == 0 else "PARTIAL" if r < q else "FULL" if r == q else "OVER"
        self.po_events = []
        grns_by_po = {}
        for g in self.grns:
            grns_by_po.setdefault(g["po_id"], []).append(g)
        lines_by_grn = {}
        for gl in self.grn_lines:
            lines_by_grn.setdefault(gl["grn_id"], []).append(gl)
        ev = 0
        for po in self.pos:
            ls = po["_lines"]
            po["line_count"] = len(ls)
            po["subtotal_amount"] = sum((ln["line_amount"] for ln in ls), Decimal("0"))
            po["tax_amount"] = sum((ln["line_tax_amount"] for ln in ls), Decimal("0"))
            po["total_amount"] = po["subtotal_amount"] + po["tax_amount"]
            ev += 1
            seq, status = 1, "CREATED"
            self.po_events.append({"event_id": f"POE-{ev:07d}", "po_id": po["po_id"], "sequence": seq,
                                   "event_date": po["po_date"], "from_status": None, "to_status": "CREATED",
                                   "source_ref": po["po_id"]})
            cum = {ln["po_line_id"]: 0 for ln in ls}
            for g in grns_by_po.get(po["po_id"], []):
                for gl in lines_by_grn[g["grn_id"]]:
                    cum[gl["po_line_id"]] += gl["quantity_received"]
                full = all(cum[ln["po_line_id"]] >= ln["quantity_ordered"] for ln in ls)
                new = "RECEIVED" if full else "PARTIALLY_RECEIVED"
                if new != status:
                    ev += 1
                    seq += 1
                    self.po_events.append({"event_id": f"POE-{ev:07d}", "po_id": po["po_id"], "sequence": seq,
                                           "event_date": g["receipt_date"], "from_status": status,
                                           "to_status": new, "source_ref": g["grn_id"]})
                    status = new
            po["status"] = status

    # ----------------------------------------------------------- 5 invoices --
    def _price_with_variance(self, po_price: Decimal, low: float, high: float, must_exceed: Decimal | None):
        price = q2(po_price * Decimal(str(1 + self.rng.uniform(low, high))))
        if must_exceed is not None:
            while (price - po_price) <= po_price * must_exceed + po_price * Decimal("0.005"):
                price += Decimal("0.01")
        return price

    def _finalise_amounts(self, inv, tax_override_line=None, wrong_rate=None):
        for ln in inv["lines"]:
            ln["line_amount"] = q2(ln["quantity"] * ln["unit_price"])
            rate = self.p.tax_rates[ln["tax_code"]]
            if tax_override_line is not None and ln is tax_override_line:
                rate = wrong_rate
            ln["line_tax_amount"] = line_tax(ln["line_amount"], rate)
        inv["subtotal_amount"] = sum((ln["line_amount"] for ln in inv["lines"]), Decimal("0"))
        inv["tax_amount"] = sum((ln["line_tax_amount"] for ln in inv["lines"]), Decimal("0"))
        inv["total_amount"] = inv["subtotal_amount"] + inv["tax_amount"]

    def make_group_invoices(self):
        rng, tol = self.rng, self.p.price_tolerance_pct
        self.invoices = []
        for n, g in enumerate(self.groups, 1):
            po, sub, t = g["po"], g["sub"], g["target"]
            vendor = self.vendor_by_id[po["vendor_id"]]
            inv = {"_key": f"G{n:06d}", "vendor_id": vendor["vendor_id"], "po_id": po["po_id"],
                   "currency": self.p.currency, "channel": vendor["invoice_channel"],
                   "scenario": g["scenario"], "sub": sub, "variant": g["variant"],
                   "target_line": t["po_line_id"], "detail": "", "duplicate_of": None,
                   "cost_center": po["cost_center"], "lines": []}
            for ln in g["lines"]:
                inv["lines"].append({"po_line_id": ln["po_line_id"], "sku": ln["sku"],
                                     "description": ln["description"], "quantity": ln["quantity_ordered"],
                                     "unit_price": ln["unit_price"], "tax_code": ln["tax_code"]})
            tl = next(x for x in inv["lines"] if x["po_line_id"] == t["po_line_id"])
            wrong_rate = None
            if sub == "within_tolerance_price":
                tl["unit_price"] = self._price_with_variance(t["unit_price"], 0.002, 0.015, None)
                inv["detail"] = f"unit price {tl['unit_price']} vs PO {t['unit_price']} (within {tol:.0%})"
            elif sub == "price_above_tolerance":
                tl["unit_price"] = self._price_with_variance(t["unit_price"], 0.03, 0.25, tol)
                pct = (tl["unit_price"] / t["unit_price"] - 1) * 100
                inv["detail"] = f"unit price {tl['unit_price']} vs PO {t['unit_price']} (+{pct:.2f}%)"
            elif sub == "partial_receipt_billed_at_received":
                tl["quantity"] = t["quantity_received"]
                inv["detail"] = f"billed {tl['quantity']} = received {t['quantity_received']} of ordered {t['quantity_ordered']}"
            elif sub == "over_receipt_billed_at_po":
                inv["detail"] = f"received {t['quantity_received']} > ordered {t['quantity_ordered']}; billed ordered qty"
            elif sub == "partial_delivery":
                inv["detail"] = f"billed {tl['quantity']} but only {t['quantity_received']} received"
            elif sub == "exceeds_po_quantity":
                tl["quantity"] = t["quantity_ordered"] + g["billed_extra"]
                inv["detail"] = (f"billed {tl['quantity']} > ordered {t['quantity_ordered']} "
                                 f"(received {t['quantity_received']})")
            elif sub == "tax_mismatch":
                po_rate = self.p.tax_rates[t["tax_code"]]
                others = [c for c, r in self.p.tax_rates.items() if r != po_rate]
                new_code = rng.choice(others)
                if g["variant"] == "wrong_amount":
                    wrong_rate = self.p.tax_rates[new_code]
                    diff = abs(line_tax(q2(tl["quantity"] * tl["unit_price"]), wrong_rate)
                               - line_tax(q2(tl["quantity"] * tl["unit_price"]), po_rate))
                    if diff < Decimal("0.05"):
                        g["variant"] = inv["variant"] = "wrong_code"
                        wrong_rate = None
                if g["variant"] == "wrong_code":
                    tl["tax_code"] = new_code
                    inv["detail"] = f"tax code {new_code} vs PO {t['tax_code']}"
                else:
                    inv["detail"] = f"tax computed at {wrong_rate} instead of {po_rate} for {t['tax_code']}"
            self._finalise_amounts(inv, tl if wrong_rate is not None else None, wrong_rate)
            if sub == "total_mismatch":
                delta = max(Decimal("1.00"), q2(inv["total_amount"] * Decimal(str(rng.uniform(0.005, 0.05)))))
                delta = delta if rng.random() < 0.5 else -delta
                inv["total_amount"] += delta
                inv["detail"] = f"stated total off by {delta} vs line sum"

            # ---- dates (derived from parent records) ----
            rdates = [d for ln in g["lines"] for d in self.receipt_dates_by_line.get(ln["po_line_id"], [])]
            last_grn = max(rdates) if rdates else None
            base = max(po["po_date"], last_grn) if last_grn else po["po_date"] + timedelta(days=rng.randint(10, 40))
            base = self._cap(base, margin=4)
            if sub == "invoice_date_before_po":
                inv["invoice_date"] = po["po_date"] - timedelta(days=rng.randint(1, 20))
                inv["received_date"] = self._cap(base + timedelta(days=rng.randint(0, 5)), floor=base)
                inv["detail"] = f"invoice dated {inv['invoice_date']} before PO date {po['po_date']}"
            else:
                inv["invoice_date"] = self._cap(base + timedelta(days=rng.randint(0, 12)), floor=base, margin=4)
                inv["received_date"] = self._cap(inv["invoice_date"] + timedelta(days=rng.randint(0, 4)),
                                                 floor=inv["invoice_date"])
            if sub == "no_goods_receipt":
                inv["detail"] = "no goods receipt posted for billed PO lines"
            self.invoices.append(inv)

    def apply_vendor_closures(self):
        rng = self.rng
        by_vendor = {}
        for inv in self.invoices:
            by_vendor.setdefault(inv["vendor_id"], []).append(inv)
        for vid in self.closed_vendor_ids:
            v = self.vendor_by_id[vid]
            closed_inv = next(i for i in by_vendor[vid] if i["sub"] == "closed_vendor")
            activity = [po["po_date"] for po in self.pos if po["vendor_id"] == vid]
            activity += [g["receipt_date"] for g in self.grns if g["vendor_id"] == vid]
            for i in by_vendor[vid]:
                if i is not closed_inv:
                    activity += [i["invoice_date"], i["received_date"]]
            last = max(activity)
            closed = last + timedelta(days=rng.randint(1, 3))
            inv_date = closed + timedelta(days=rng.randint(1, 3))
            recv = inv_date + timedelta(days=rng.randint(0, 1))
            if recv > self.as_of:
                shift = (recv - self.as_of).days
                closed, inv_date, recv = (closed - timedelta(days=shift), inv_date - timedelta(days=shift),
                                          self.as_of)
            if closed <= last:
                raise GenerationError(f"cannot place closure for {vid} before as-of date")
            v["status"], v["closed_date"] = "CLOSED", closed
            closed_inv["invoice_date"], closed_inv["received_date"] = inv_date, recv
            closed_inv["detail"] = f"vendor closed {closed}; invoice dated {inv_date}"
        # dormant vendors (no POs) closed in 2025 - realistic master data, no invoices
        used = {po["vendor_id"] for po in self.pos}
        dormant = [v for v in self.vendors if v["vendor_id"] not in used]
        for v in dormant[: max(1, len(self.vendors) * 3 // 100)]:
            v["status"] = "CLOSED"
            v["closed_date"] = max(v["onboarded_date"] + timedelta(days=30), date(2025, 6, 30))

    def make_non_po_invoices(self):
        rng = self.rng
        active = [v for v in self.vendors if v["status"] == "ACTIVE"]
        srv = [s for s, it in self.catalog.items() if it["category"] == "SRV"]
        for n in range(1, self.n_nonpo + 1):
            v = rng.choice(active)
            inv = {"_key": f"N{n:06d}", "vendor_id": v["vendor_id"], "po_id": None, "currency": self.p.currency,
                   "channel": v["invoice_channel"], "scenario": "clean", "sub": "non_po", "variant": "",
                   "target_line": None, "detail": "service invoice without PO", "duplicate_of": None,
                   "cost_center": rng.choice(cat.COST_CENTERS), "lines": []}
            for sku in rng.sample(srv, rng.randint(1, 3)):
                item = self.catalog[sku]
                inv["lines"].append({"po_line_id": None, "sku": sku, "description": item["description"],
                                     "quantity": rng.randint(1, 15),
                                     "unit_price": q2(item["base_price"] * Decimal(str(rng.uniform(0.95, 1.05)))),
                                     "tax_code": item["tax_code"]})
            self._finalise_amounts(inv)
            inv["invoice_date"] = self._date_between(self.p.po_start, self.as_of - timedelta(days=10))
            inv["received_date"] = inv["invoice_date"] + timedelta(days=rng.randint(0, 4))
            self.invoices.append(inv)

    def assign_vendor_invoice_numbers(self):
        by_vendor = {}
        for inv in self.invoices:
            by_vendor.setdefault(inv["vendor_id"], []).append(inv)
        yy = str(self.year)[2:]
        for vid in sorted(by_vendor):
            v = self.vendor_by_id[vid]
            for k, inv in enumerate(sorted(by_vendor[vid], key=lambda i: (i["invoice_date"], i["_key"]))):
                seq = v["_num_start"] + k
                style = v["_num_style"]
                if style == 0:
                    num = f"{v['vendor_code']}-{yy}-{seq:04d}"
                elif style == 1:
                    num = f"INV{seq:06d}"
                else:
                    num = f"{v['vendor_code'][:3]}/{self.year}/{seq:05d}"
                inv["vendor_invoice_number"] = num

    def make_duplicates(self):
        rng = self.rng
        closed = set(self.closed_vendor_ids)
        pool = [i for i in self.invoices if i["sub"] == "standard" and i["vendor_id"] not in closed
                and i["received_date"] <= self.as_of - timedelta(days=22)]
        pool.sort(key=lambda i: i["_key"])
        originals = rng.sample(pool, self.n_dup)
        subs = self.sub_mix["duplicate"]
        kinds = ["same_invoice_submitted_twice"] * subs["same_invoice_submitted_twice"] + \
                ["duplicate_invoice_number"] * subs["duplicate_invoice_number"]
        for n, (orig, kind) in enumerate(zip(originals, kinds), 1):
            dup = {k: v for k, v in orig.items() if k != "lines"}
            dup["lines"] = [dict(ln) for ln in orig["lines"]]
            dup.update({"_key": f"D{n:06d}", "scenario": "duplicate", "sub": kind, "variant": "",
                        "duplicate_of": orig["_key"], "target_line": None})
            if kind == "same_invoice_submitted_twice":
                dup["received_date"] = orig["received_date"] + timedelta(days=rng.randint(1, 20))
                if rng.random() < 0.5:   # resent through another channel -> different layout
                    dup["channel"] = rng.choice([c for c in ("EMAIL", "PORTAL", "EDI") if c != orig["channel"]])
                if rng.random() < 0.5:   # number typed differently, same after normalisation
                    num = orig["vendor_invoice_number"]
                    dup["vendor_invoice_number"] = num.lower() if rng.random() < 0.5 else \
                        num.replace("-", "").replace("/", "")
                dup["detail"] = f"resubmission of {orig['vendor_invoice_number']} via {dup['channel']}"
            else:
                dup["invoice_date"] = orig["invoice_date"] + timedelta(days=rng.randint(5, 30))
                ln = rng.choice(dup["lines"])
                ln["quantity"] = ln["quantity"] + rng.randint(1, max(1, ln["quantity"] // 4))
                self._finalise_amounts(dup)
                dup["received_date"] = self._cap(max(orig["received_date"] + timedelta(days=1), dup["invoice_date"])
                                                 + timedelta(days=rng.randint(0, 3)))
                dup["invoice_date"] = min(dup["invoice_date"], dup["received_date"])
                dup["detail"] = f"number {orig['vendor_invoice_number']} reused with total {dup['total_amount']}"
            self.invoices.append(dup)

    # ----------------------------------------------- 7 intake order + IDs --
    def assign_invoice_ids(self):
        self.invoices.sort(key=lambda i: (i["received_date"], i["_key"]))
        key_to_id = {}
        for n, inv in enumerate(self.invoices, 1):
            v = self.vendor_by_id[inv["vendor_id"]]
            inv["invoice_id"] = ids.invoice_id(v["vendor_code"], n, self.year)
            inv["document_id"] = ids.document_id(n, self.year)
            key_to_id[inv["_key"]] = inv["invoice_id"]
            for k, ln in enumerate(inv["lines"], 1):
                ln["invoice_line_id"] = ids.invoice_line_id(inv["invoice_id"], k)
                ln["line_number"] = k
        for inv in self.invoices:
            if inv["duplicate_of"]:
                inv["duplicate_of"] = key_to_id[inv["duplicate_of"]]
        self.documents = [{"document_id": inv["document_id"], "invoice_id": inv["invoice_id"],
                           "received_date": inv["received_date"].isoformat(), "channel": inv["channel"],
                           "content": render(inv, self.vendor_by_id[inv["vendor_id"]], inv["channel"])}
                          for inv in self.invoices]

    # ------------------------------------- 8 ground truth / approvals / pay --
    def derive_outcomes(self):
        self.ground_truth, self.approvals, self.payments = [], [], []
        for inv in self.invoices:
            key = (inv["scenario"], inv["sub"], inv["variant"])
            expected = EXPECTED_EXCEPTIONS[key]
            non_po = inv["po_id"] is None
            eligible = not expected
            roles = self.p.approval_roles(inv["total_amount"], non_po) if eligible else []
            self.ground_truth.append({
                "invoice_id": inv["invoice_id"], "scenario": inv["scenario"], "sub_scenario": inv["sub"],
                "variant": inv["variant"], "issue_type": primary_exception(expected),
                "target_line": inv["target_line"], "injected_detail": inv["detail"],
                "duplicate_of_invoice_id": inv["duplicate_of"],
                "expected_exceptions": "|".join(sorted(expected)),
                "expected_primary_exception": primary_exception(expected),
                "expected_match_status": match_status_for(expected, non_po),
                "expected_route_queue": queue_for(expected),
                "expected_approval_roles": "|".join(roles),
                "expected_payment_ready": eligible,
            })
            if not eligible:
                continue
            tier = self.p.approval_tier(inv["total_amount"], non_po)["tier"]
            d = inv["received_date"]
            for level, role in enumerate(roles, 1):
                d = min(self.as_of, d + timedelta(days=0 if role == "SYSTEM_AUTO" else self.rng.randint(1, 3)))
                approver = {"SYSTEM_AUTO": "SYSTEM", "DEPT_MANAGER": f"MGR-{inv['cost_center']}",
                            "FINANCE_CONTROLLER": "CTRL-01"}[role]
                self.approvals.append({"approval_id": ids.approval_id(len(self.approvals) + 1, self.year),
                                       "invoice_id": inv["invoice_id"], "level": level, "approver_role": role,
                                       "approver_id": approver, "policy_tier": tier, "decision": "APPROVED",
                                       "decided_date": d})
            v = self.vendor_by_id[inv["vendor_id"]]
            due = inv["invoice_date"] + timedelta(days=v["payment_terms_days"])
            sched = max(due, d)
            paid = sched <= self.as_of
            self.payments.append({"payment_id": ids.payment_id(len(self.payments) + 1, self.year),
                                  "invoice_id": inv["invoice_id"], "vendor_id": v["vendor_id"],
                                  "amount": inv["total_amount"], "currency": inv["currency"],
                                  "method": v["payment_method"], "due_date": due, "scheduled_date": sched,
                                  "status": "PAID" if paid else "SCHEDULED", "paid_date": sched if paid else None})

    # --------------------------------------------------------------- run --
    def run(self) -> dict:
        self.make_vendors()
        self.make_purchase_orders()
        self.plan_invoices()
        self.make_receipts()
        self.make_group_invoices()
        self.apply_vendor_closures()
        self.make_non_po_invoices()
        self.assign_vendor_invoice_numbers()
        self.make_duplicates()
        self.assign_invoice_ids()
        self.derive_outcomes()
        return self.tables()

    def tables(self) -> dict:
        def strip(rows):
            return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

        invoices, inv_lines = [], []
        for inv in self.invoices:
            invoices.append({"invoice_id": inv["invoice_id"], "document_id": inv["document_id"],
                             "vendor_id": inv["vendor_id"], "po_id": inv["po_id"],
                             "vendor_invoice_number": inv["vendor_invoice_number"],
                             "invoice_date": inv["invoice_date"], "received_date": inv["received_date"],
                             "channel": inv["channel"], "currency": inv["currency"],
                             "line_count": len(inv["lines"]), "subtotal_amount": inv["subtotal_amount"],
                             "tax_amount": inv["tax_amount"], "total_amount": inv["total_amount"]})
            for ln in inv["lines"]:
                inv_lines.append({"invoice_line_id": ln["invoice_line_id"], "invoice_id": inv["invoice_id"],
                                  "line_number": ln["line_number"], "po_line_id": ln["po_line_id"],
                                  "sku": ln["sku"], "description": ln["description"], "quantity": ln["quantity"],
                                  "unit_price": ln["unit_price"], "tax_code": ln["tax_code"],
                                  "line_amount": ln["line_amount"], "line_tax_amount": ln["line_tax_amount"]})
        return {
            "vendors": strip(self.vendors),
            "purchase_orders": strip(self.pos),
            "purchase_order_lines": strip(self.po_lines),
            "purchase_order_events": self.po_events,
            "goods_receipts": self.grns,
            "goods_receipt_lines": self.grn_lines,
            "invoices": invoices,
            "invoice_lines": inv_lines,
            "approvals": self.approvals,
            "payments": self.payments,
            "ground_truth": self.ground_truth,
            "_documents": self.documents,
        }


def generate(policy: Policy) -> dict:
    return Generator(policy).run()
