"""Deterministic, zero-padded, immutable identifiers.

Conventions (from the problem statement, plus documented extensions):
    Vendor          VND-00001
    PurchaseOrder   PO-2026-000001
    PO line         PO-2026-000001-01            (extension)
    GoodsReceipt    GRN-2026-000001
    Receipt line    GRN-2026-000001-01           (extension)
    Invoice         INV-<vendor-code>-2026-000001
    Invoice line    INVL-<invoice-id>-01
    Approval        APR-2026-000001              (extension)
    Payment         PAY-2026-000001              (extension)
"""

import re


def vendor_id(n: int) -> str:
    return f"VND-{n:05d}"


def po_id(n: int, year: int) -> str:
    return f"PO-{year}-{n:06d}"


def po_line_id(po: str, line_no: int) -> str:
    return f"{po}-{line_no:02d}"


def grn_id(n: int, year: int) -> str:
    return f"GRN-{year}-{n:06d}"


def grn_line_id(grn: str, line_no: int) -> str:
    return f"{grn}-{line_no:02d}"


def invoice_id(vendor_code: str, n: int, year: int) -> str:
    return f"INV-{vendor_code}-{year}-{n:06d}"


def invoice_line_id(inv: str, line_no: int) -> str:
    return f"INVL-{inv}-{line_no:02d}"


def approval_id(n: int, year: int) -> str:
    return f"APR-{year}-{n:06d}"


def payment_id(n: int, year: int) -> str:
    return f"PAY-{year}-{n:06d}"


def document_id(n: int, year: int) -> str:
    return f"DOC-{year}-{n:06d}"


PATTERNS = {
    "vendor_id": r"^VND-\d{5}$",
    "vendor_code": r"^[A-Z]{3}\d{2}$",
    "po_id": r"^PO-\d{4}-\d{6}$",
    "po_line_id": r"^PO-\d{4}-\d{6}-\d{2}$",
    "grn_id": r"^GRN-\d{4}-\d{6}$",
    "grn_line_id": r"^GRN-\d{4}-\d{6}-\d{2}$",
    "invoice_id": r"^INV-[A-Z]{3}\d{2}-\d{4}-\d{6}$",
    "invoice_line_id": r"^INVL-INV-[A-Z]{3}\d{2}-\d{4}-\d{6}-\d{2}$",
    "approval_id": r"^APR-\d{4}-\d{6}$",
    "payment_id": r"^PAY-\d{4}-\d{6}$",
    "document_id": r"^DOC-\d{4}-\d{6}$",
}

_COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}


def is_valid(kind: str, value: str) -> bool:
    return bool(_COMPILED[kind].match(value or ""))
