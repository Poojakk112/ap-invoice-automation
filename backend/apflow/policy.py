"""Business rule catalogue: exception codes, precedence, routing and lifecycle.

This is the single documented rule table. The generator uses it to derive
ground-truth labels from the scenario it injected; the pipeline uses the same
codes/queues when it detects issues independently from the raw documents.
"""

# code -> (severity, owning queue, match status, description)
EXCEPTIONS = {
    "EXTRACTION_FAILED": ("BLOCK", "AP_DATA_QUALITY", "HEADER_ERROR",
                          "Document could not be parsed into required fields"),
    "DUPLICATE_EXACT": ("BLOCK", "AP_DUPLICATE_REVIEW", "DUPLICATE",
                        "Same vendor, invoice number, date and amount already received"),
    "DUPLICATE_NUMBER": ("BLOCK", "AP_DUPLICATE_REVIEW", "DUPLICATE",
                         "Vendor re-used an invoice number with different content"),
    "VENDOR_UNKNOWN": ("BLOCK", "VENDOR_MASTER", "VENDOR_BLOCKED",
                       "Supplier tax ID / name not found in vendor master"),
    "VENDOR_INACTIVE": ("BLOCK", "VENDOR_MASTER", "VENDOR_BLOCKED",
                        "Vendor was closed before the invoice date"),
    "VENDOR_PO_MISMATCH": ("BLOCK", "PROCUREMENT", "VENDOR_BLOCKED",
                           "Invoice vendor differs from PO vendor"),
    "TOTAL_MISMATCH": ("BLOCK", "AP_DATA_QUALITY", "HEADER_ERROR",
                       "Stated subtotal/total does not equal the sum of lines plus tax"),
    "DATE_BEFORE_PO": ("BLOCK", "AP_DATA_QUALITY", "HEADER_ERROR",
                       "Invoice is dated before the purchase order"),
    "PO_NOT_FOUND": ("BLOCK", "PROCUREMENT", "HEADER_ERROR",
                     "Referenced PO does not exist"),
    "TAX_MISMATCH": ("BLOCK", "TAX_TEAM", "TAX_VARIANCE",
                     "Tax code differs from PO or tax amount does not reconcile"),
    "LINE_NOT_ON_PO": ("BLOCK", "PROCUREMENT", "QUANTITY_VARIANCE",
                       "Invoiced SKU is not on the purchase order"),
    "MISSING_RECEIPT": ("BLOCK", "RECEIVING", "NO_RECEIPT",
                        "No goods receipt posted for an invoiced PO line"),
    "QTY_EXCEEDS_PO": ("BLOCK", "PROCUREMENT", "QUANTITY_VARIANCE",
                       "Cumulative invoiced quantity exceeds ordered quantity"),
    "QTY_EXCEEDS_RECEIVED": ("BLOCK", "RECEIVING", "QUANTITY_VARIANCE",
                             "Cumulative invoiced quantity exceeds received quantity"),
    "PRICE_VARIANCE": ("BLOCK", "PROCUREMENT", "PRICE_VARIANCE",
                       "Unit price above PO price beyond tolerance"),
}

# When an invoice has several exceptions, the first one in this list decides
# the primary queue (most fundamental problem first).
PRECEDENCE = [
    "EXTRACTION_FAILED", "DUPLICATE_EXACT", "DUPLICATE_NUMBER", "VENDOR_UNKNOWN", "VENDOR_INACTIVE",
    "VENDOR_PO_MISMATCH", "PO_NOT_FOUND", "TOTAL_MISMATCH", "DATE_BEFORE_PO",
    "TAX_MISMATCH", "MISSING_RECEIPT", "LINE_NOT_ON_PO", "QTY_EXCEEDS_PO",
    "QTY_EXCEEDS_RECEIVED", "PRICE_VARIANCE",
]

MATCH_STATUSES = sorted({v[2] for v in EXCEPTIONS.values()} | {"MATCHED", "NON_PO"})
QUEUES = sorted({v[1] for v in EXCEPTIONS.values()})


def primary_exception(codes) -> str:
    codes = set(codes)
    for code in PRECEDENCE:
        if code in codes:
            return code
    return ""


def match_status_for(codes, non_po: bool) -> str:
    primary = primary_exception(codes)
    if primary:
        return EXCEPTIONS[primary][2]
    return "NON_PO" if non_po else "MATCHED"


def queue_for(codes) -> str:
    primary = primary_exception(codes)
    return EXCEPTIONS[primary][1] if primary else ""


# Ground-truth rule table: scenario/sub-scenario/variant -> expected exceptions.
EXPECTED_EXCEPTIONS = {
    ("clean", "standard", ""): [],
    ("clean", "within_tolerance_price", ""): [],
    ("clean", "partial_receipt_billed_at_received", ""): [],
    ("clean", "over_receipt_billed_at_po", ""): [],
    ("clean", "non_po", ""): [],
    ("price_variance", "price_above_tolerance", ""): ["PRICE_VARIANCE"],
    ("quantity_mismatch", "partial_delivery", ""): ["QTY_EXCEEDS_RECEIVED"],
    ("quantity_mismatch", "exceeds_po_quantity", "received_as_ordered"): ["QTY_EXCEEDS_PO", "QTY_EXCEEDS_RECEIVED"],
    ("quantity_mismatch", "exceeds_po_quantity", "over_received"): ["QTY_EXCEEDS_PO"],
    ("duplicate", "same_invoice_submitted_twice", ""): ["DUPLICATE_EXACT"],
    ("duplicate", "duplicate_invoice_number", ""): ["DUPLICATE_NUMBER"],
    ("missing_receipt", "no_goods_receipt", ""): ["MISSING_RECEIPT"],
    ("tax_vendor_error", "tax_mismatch", "wrong_code"): ["TAX_MISMATCH"],
    ("tax_vendor_error", "tax_mismatch", "wrong_amount"): ["TAX_MISMATCH"],
    ("tax_vendor_error", "closed_vendor", ""): ["VENDOR_INACTIVE"],
    ("tax_vendor_error", "total_mismatch", ""): ["TOTAL_MISMATCH"],
    ("tax_vendor_error", "invoice_date_before_po", ""): ["DATE_BEFORE_PO"],
}

# Invoice lifecycle (append-only events must follow these transitions).
INVOICE_TRANSITIONS = {
    None: {"RECEIVED"},
    "RECEIVED": {"EXTRACTED", "EXCEPTION_ROUTED"},
    "EXTRACTED": {"VALIDATED", "DUPLICATE_BLOCKED"},
    "VALIDATED": {"MATCHED", "EXCEPTION_ROUTED"},
    "MATCHED": {"APPROVAL_PENDING"},
    "APPROVAL_PENDING": {"APPROVED"},
    "APPROVED": {"APPROVED", "PAYMENT_READY"},
    "DUPLICATE_BLOCKED": set(),
    "EXCEPTION_ROUTED": set(),
    "PAYMENT_READY": set(),
}

PO_TRANSITIONS = {
    None: {"CREATED"},
    "CREATED": {"PARTIALLY_RECEIVED", "RECEIVED"},
    "PARTIALLY_RECEIVED": {"PARTIALLY_RECEIVED", "RECEIVED"},
    "RECEIVED": set(),
}

BLOCKED_STATES = {"DUPLICATE_BLOCKED", "EXCEPTION_ROUTED"}
