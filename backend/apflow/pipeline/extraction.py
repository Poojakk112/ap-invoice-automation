"""Intake + field extraction from raw invoice documents.

Detects the layout, then parses header fields and lines with regular
expressions. Dates and amounts are normalised (DD/MM/YYYY, DD-Mon-YYYY,
'$1,234.50' -> ISO date / Decimal). Anything that cannot be parsed is reported
as an extraction error instead of being guessed.

This is deliberately rule-based: deterministic, explainable and testable. The
`extract()` function is the seam where an OCR/LLM extractor could be plugged in
later, and the evaluation harness would score it the same way.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from apflow.money import D

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


class ExtractionError(ValueError):
    pass


@dataclass
class ExtractedLine:
    line_number: int
    sku: str
    description: str
    quantity: int
    unit_price: Decimal
    tax_code: str
    line_amount: Decimal


@dataclass
class ExtractedInvoice:
    layout: str
    vendor_name: str
    vendor_tax_id: str
    vendor_invoice_number: str
    invoice_date: date
    po_number: str | None
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    stated_total: Decimal
    lines: list = field(default_factory=list)


def parse_date(text: str) -> date:
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):            # DD/MM/YYYY
        return datetime.strptime(text, "%d/%m/%Y").date()
    m = re.fullmatch(r"(\d{2})-([A-Z][a-z]{2})-(\d{4})", text)
    if m and m.group(2) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    raise ExtractionError(f"unrecognised date format: {text!r}")


def parse_amount(text: str) -> Decimal:
    cleaned = text.strip().replace("$", "").replace(",", "").replace("USD", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", cleaned):
        raise ExtractionError(f"unrecognised amount: {text!r}")
    return D(cleaned)


def _field(pattern: str, text: str, name: str) -> str:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise ExtractionError(f"missing field: {name}")
    return m.group(1).strip()


def _po(value: str):
    return None if value.strip().upper() in ("N/A", "-", "NONE", "") else value.strip()


def detect_layout(content: str) -> str:
    stripped = content.strip()
    first = stripped.splitlines()[0].strip() if stripped else ""
    layout = {"TAX INVOICE": "A", "INVOICE": "B", "BEGIN INVOICE": "C"}.get(first)
    if layout is None:
        raise ExtractionError(f"unknown layout header: {first!r}")
    return layout


def _extract_a(c):
    lines = []
    for m in re.finditer(r"^(\d+) \| (SKU-\S+) \| (.+?) \| (\d+) \| ([\d,\.]+) \| (TX\d+) \| ([\d,\.\-]+)$", c, re.M):
        lines.append(ExtractedLine(int(m[1]), m[2], m[3], int(m[4]), parse_amount(m[5]), m[6], parse_amount(m[7])))
    return ExtractedInvoice(
        layout="A",
        vendor_name=_field(r"^Supplier: (.+)$", c, "vendor_name"),
        vendor_tax_id=_field(r"^Supplier Tax ID: (.+)$", c, "tax_id"),
        vendor_invoice_number=_field(r"^Invoice No: (.+)$", c, "invoice_number"),
        invoice_date=parse_date(_field(r"^Invoice Date: (.+)$", c, "invoice_date")),
        po_number=_po(_field(r"^PO Number: (.+)$", c, "po_number")),
        currency=_field(r"^Currency: (\w{3})$", c, "currency"),
        subtotal=parse_amount(_field(r"^Subtotal: (.+)$", c, "subtotal")),
        tax_total=parse_amount(_field(r"^Tax: (.+)$", c, "tax")),
        stated_total=parse_amount(_field(r"^Total Due: (.+)$", c, "total")),
        lines=lines,
    )


def _extract_b(c):
    lines = []
    pat = (r"^- (SKU-\S+) ; (.+?) ; qty=(\d+) ; price=\$([\d,\.]+) ; tax=(TX\d+) ; line=\$([\d,\.\-]+)$")
    for i, m in enumerate(re.finditer(pat, c, re.M), 1):
        lines.append(ExtractedLine(i, m[1], m[2], int(m[3]), parse_amount(m[4]), m[5], parse_amount(m[6])))
    vendor = re.search(r"^From: (.+) \(TIN (.+)\)$", c, re.M)
    if not vendor:
        raise ExtractionError("missing field: vendor")
    total = re.search(r"^TOTAL (\w{3}) \$(.+)$", c, re.M)
    if not total:
        raise ExtractionError("missing field: total")
    return ExtractedInvoice(
        layout="B",
        vendor_name=vendor[1].strip(), vendor_tax_id=vendor[2].strip(),
        vendor_invoice_number=_field(r"^Inv #: (.+)$", c, "invoice_number"),
        invoice_date=parse_date(_field(r"^Date: (.+)$", c, "invoice_date")),
        po_number=_po(_field(r"^Customer PO: (.+)$", c, "po_number")),
        currency=total[1],
        subtotal=parse_amount(_field(r"^SUBTOTAL (.+)$", c, "subtotal")),
        tax_total=parse_amount(_field(r"^TAX (.+)$", c, "tax")),
        stated_total=parse_amount(total[2]),
        lines=lines,
    )


def _extract_c(c):
    kv = dict(re.findall(r"^([A-Z_]+)=(.*)$", c, re.M))
    lines = []
    for m in re.finditer(r"^LINE\|(\d+)\|(SKU-[^|]+)\|([^|]+)\|(\d+)\|([\d\.]+)\|(TX\d+)\|([\d\.\-]+)$", c, re.M):
        lines.append(ExtractedLine(int(m[1]), m[2], m[3], int(m[4]), parse_amount(m[5]), m[6], parse_amount(m[7])))
    try:
        return ExtractedInvoice(
            layout="C",
            vendor_name=kv["SUPPLIER_NAME"], vendor_tax_id=kv["SUPPLIER_TAX_ID"],
            vendor_invoice_number=kv["DOC_NUMBER"], invoice_date=parse_date(kv["DOC_DATE"]),
            po_number=_po(kv["ORDER_REF"]), currency=kv["CURRENCY"],
            subtotal=parse_amount(kv["TOTAL_NET"]), tax_total=parse_amount(kv["TOTAL_TAX"]),
            stated_total=parse_amount(kv["TOTAL_GROSS"]), lines=lines,
        )
    except KeyError as exc:
        raise ExtractionError(f"missing field: {exc.args[0]}") from exc


_ITEM_START = re.compile(r"^(?:\d+ \| SKU-|- SKU-|LINE\|)", re.M)


def normalise_text(content: str) -> str:
    """Windows/Mac line endings and trailing spaces must not change the result."""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def extract(content: str) -> ExtractedInvoice:
    content = normalise_text(content)
    layout = detect_layout(content)
    inv = {"A": _extract_a, "B": _extract_b, "C": _extract_c}[layout](content)
    if not inv.lines:
        raise ExtractionError("no invoice lines found")
    seen = len(_ITEM_START.findall(content))
    if seen != len(inv.lines):      # never silently drop a line we could not read
        raise ExtractionError(f"{seen} item lines found but only {len(inv.lines)} could be read")
    return inv


def normalise_invoice_number(number: str) -> str:
    """'abc-26-0012', 'ABC260012' and ' ABC-26-0012 ' all map to 'ABC260012'."""
    return re.sub(r"[^A-Z0-9]", "", number.upper())
