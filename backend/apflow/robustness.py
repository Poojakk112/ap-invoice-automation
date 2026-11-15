"""Robustness test: how does the pipeline behave when invoice documents are damaged?

The generated documents are perfectly clean, so a 100% extraction score proves
little. This module damages a seeded sample of documents in six realistic ways
(OCR confusions, a changed digit, a missing total, a missing PO reference,
messy whitespace) and measures what happens to each damaged invoice:

    HANDLED_OK            decision unchanged by the damage
    SAFE_FAILURE          blocked or routed to a person (extraction failure, mismatch, ...)
    STILL_BLOCKED         was already an exception; still blocked
    UNSAFE_PAYMENT        made payment-ready although it must not be, or with a wrong amount

The number that matters is UNSAFE_PAYMENT: damage must never cause a wrong payment.
"""

import random
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from apflow.config import Policy
from apflow.export import read_csv, write_json
from apflow.money import D
from apflow.pipeline.run import decide, load_inputs

AMOUNT = re.compile(r"\d[\d,]*\.\d{2}")
TOTAL_LINE = re.compile(r"(?im)^(total due:|total usd|total_gross=).*$")
ITEM_LINE = re.compile(r"(?m)^(\d+ \| SKU-.*|- SKU-.*|LINE\|.*)$")
PO_SUBS = [(re.compile(r"(?m)^(PO Number: ).+$"), r"\1N/A"),
           (re.compile(r"(?m)^(Customer PO: ).+$"), r"\1-"),
           (re.compile(r"(?m)^(ORDER_REF=).+$"), r"\1NONE")]
DIGIT_TO_LETTER = {"0": "O", "1": "l", "2": "Z", "3": "E", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B", "9": "g"}

NOISE_DESCRIPTIONS = {
    "digit_changed_line_amount": "One digit in an item line amount is wrong (OCR misread)",
    "digit_changed_total": "One digit in the invoice total is wrong",
    "letter_for_digit": "A digit in an item amount is read as a letter (O for 0, l for 1, ...)",
    "missing_total": "The total line is missing (page cut off)",
    "missing_po_reference": "The PO number is blank or unreadable",
    "messy_whitespace": "Windows line endings and trailing spaces",
}


def _bump_digit(token: str) -> str:
    idx = [i for i, c in enumerate(token) if c.isdigit()]
    i = idx[0]
    return token[:i] + str((int(token[i]) + 3) % 10) + token[i + 1:]


def _edit_last_amount(line: str, fn) -> str:
    matches = list(AMOUNT.finditer(line))
    if not matches:
        return line
    m = matches[-1]
    return line[:m.start()] + fn(m.group()) + line[m.end():]


def _first_item_line(text):
    m = ITEM_LINE.search(text)
    return m.group() if m else None


def damage(text: str, kind: str):
    """Return the damaged text, or None if this damage cannot apply to the document."""
    if kind == "digit_changed_line_amount":
        line = _first_item_line(text)
        return text.replace(line, _edit_last_amount(line, _bump_digit), 1) if line else None
    if kind == "digit_changed_total":
        m = TOTAL_LINE.search(text)
        return text.replace(m.group(), _edit_last_amount(m.group(), _bump_digit), 1) if m else None
    if kind == "letter_for_digit":
        line = _first_item_line(text)
        if not line:
            return None
        return text.replace(line, _edit_last_amount(
            line, lambda t: next(t[:i] + DIGIT_TO_LETTER[c] + t[i + 1:] for i, c in enumerate(t) if c.isdigit())), 1)
    if kind == "missing_total":
        m = TOTAL_LINE.search(text)
        return TOTAL_LINE.sub("", text, count=1).replace("\n\n", "\n").rstrip("\n") if m else None
    if kind == "missing_po_reference":
        for rx, repl in PO_SUBS:
            if rx.search(text):
                new = rx.sub(repl, text, count=1)
                return new if new != text else None
        return None
    if kind == "messy_whitespace":
        return "\r\n".join(line + "  " for line in text.split("\n"))
    raise ValueError(kind)


def run_robustness(data_dir, policy: Policy, sample: int = 150) -> dict:
    data_dir = Path(data_dir)
    tables = load_inputs(data_dir)
    gt = {r["invoice_id"]: r for r in read_csv(data_dir / "ground_truth" / "ground_truth.csv")}
    true_total = {r["invoice_id"]: D(r["total_amount"]) for r in read_csv(data_dir / "reference" / "invoices.csv")}
    baseline = {d.invoice_id: d for d in decide(tables, policy)}
    docs = tables["_documents"]
    results = {}
    for kind in NOISE_DESCRIPTIONS:
        rng = random.Random(f"{policy.seed}-{kind}")
        candidates = [d for d in docs if damage(d["content"], kind) not in (None, d["content"])]
        chosen = {d["invoice_id"] for d in rng.sample(candidates, min(sample, len(candidates)))}
        damaged = [dict(d, content=damage(d["content"], kind)) if d["invoice_id"] in chosen else d for d in docs]
        out = Counter()
        caught_by = Counter()
        unsafe = []
        collateral = 0
        for dec in decide(tables, policy, damaged):
            iid = dec.invoice_id
            if iid not in chosen:
                collateral += dec.codes != baseline[iid].codes
                continue
            g = gt[iid]
            truth_ready = g["expected_payment_ready"] == "true"
            if dec.payment_ready:
                wrong_amount = abs(dec.stated_total - true_total[iid]) > Decimal("0.005")
                if not truth_ready or wrong_amount:
                    out["UNSAFE_PAYMENT"] += 1
                    unsafe.append({"invoice_id": iid, "why": "payment-ready although it must be blocked"
                                   if not truth_ready else "payment-ready with a wrong amount",
                                   "expected_exceptions": g["expected_exceptions"]})
                else:
                    out["HANDLED_OK"] += 1
            else:
                caught_by[dec.primary] += 1
                out["SAFE_FAILURE" if truth_ready or dec.primary == "EXTRACTION_FAILED" else "STILL_BLOCKED"] += 1
        n = len(chosen)
        results[kind] = {"description": NOISE_DESCRIPTIONS[kind], "documents_damaged": n,
                         "outcomes": {k: out.get(k, 0) for k in ("HANDLED_OK", "SAFE_FAILURE", "STILL_BLOCKED", "UNSAFE_PAYMENT")},
                         "unsafe_payment_rate": round(out.get("UNSAFE_PAYMENT", 0) / n, 4) if n else 0.0,
                         "caught_by": dict(sorted(caught_by.items())),
                         "collateral_decision_changes": collateral, "unsafe_examples": unsafe[:3]}
    total_damaged = sum(r["documents_damaged"] for r in results.values())
    total_unsafe = sum(r["outcomes"]["UNSAFE_PAYMENT"] for r in results.values())
    return {"sample_per_type": sample, "seed": policy.seed, "documents_damaged": total_damaged,
            "unsafe_payments": total_unsafe,
            "safe_handling_rate": round(1 - total_unsafe / total_damaged, 4) if total_damaged else 1.0,
            "by_damage_type": results}


def robustness_markdown(r: dict) -> str:
    lines = ["# Robustness test", "",
             "Damaged documents are generated from the clean ones with a fixed seed. "
             "The key number is **unsafe payments**: damage must never turn into a wrong payment.", "",
             f"**{r['documents_damaged']} damaged documents, {r['unsafe_payments']} unsafe payments.**", "",
             "| Damage | Docs | Handled OK | Safely blocked | Still blocked | Unsafe | Caught by |",
             "|---|---|---|---|---|---|---|"]
    for kind, x in r["by_damage_type"].items():
        o = x["outcomes"]
        caught = ", ".join(f"{k} ({v})" for k, v in x["caught_by"].items()) or "-"
        lines.append(f"| {x['description']} | {x['documents_damaged']} | {o['HANDLED_OK']} | {o['SAFE_FAILURE']} | "
                     f"{o['STILL_BLOCKED']} | **{o['UNSAFE_PAYMENT']}** | {caught} |")
    lines += ["", "*Safely blocked* means a good invoice was stopped and routed to a person, which costs review time "
              "but pays nothing wrongly. *Unsafe* means money would have moved incorrectly."]
    return "\n".join(lines) + "\n"


def save(r: dict, out_dir: Path):
    write_json(out_dir / "robustness.json", r)
    (out_dir / "robustness.md").write_text(robustness_markdown(r), encoding="utf-8", newline="\n")
