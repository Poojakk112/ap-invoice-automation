"""Render invoices as raw text documents, the way they arrive at intake.

Three layouts mimic real channels, each with different labels, date formats
and number formats, so extraction has to do real work:
    EMAIL  -> layout A (pipe table, ISO dates, 1,234.56)
    PORTAL -> layout B (semicolon items, DD/MM/YYYY, $1,234.56)
    EDI    -> layout C (KEY=VALUE + LINE| records, DD-Mon-YYYY, 1234.56)
"""

from apflow.money import fmt, fmt_thousands

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def render(inv: dict, vendor: dict, channel: str) -> str:
    if channel == "EMAIL":
        return _layout_a(inv, vendor)
    if channel == "PORTAL":
        return _layout_b(inv, vendor)
    return _layout_c(inv, vendor)


def _layout_a(inv, vendor):
    d = inv["invoice_date"]
    rows = [
        "TAX INVOICE",
        f"Supplier: {vendor['vendor_name']}",
        f"Supplier Tax ID: {vendor['tax_id']}",
        f"Invoice No: {inv['vendor_invoice_number']}",
        f"Invoice Date: {d.isoformat()}",
        f"PO Number: {inv['po_id'] or 'N/A'}",
        f"Currency: {inv['currency']}",
        "-" * 60,
        "Ln | SKU | Description | Qty | Unit Price | Tax Code | Amount",
    ]
    for i, ln in enumerate(inv["lines"], 1):
        rows.append(f"{i} | {ln['sku']} | {ln['description']} | {ln['quantity']} | "
                    f"{fmt_thousands(ln['unit_price'])} | {ln['tax_code']} | {fmt_thousands(ln['line_amount'])}")
    rows += [
        "-" * 60,
        f"Subtotal: {fmt_thousands(inv['subtotal_amount'])}",
        f"Tax: {fmt_thousands(inv['tax_amount'])}",
        f"Total Due: {fmt_thousands(inv['total_amount'])}",
    ]
    return "\n".join(rows)


def _layout_b(inv, vendor):
    d = inv["invoice_date"]
    rows = [
        "INVOICE",
        f"From: {vendor['vendor_name']} (TIN {vendor['tax_id']})",
        f"Inv #: {inv['vendor_invoice_number']}",
        f"Date: {d.day:02d}/{d.month:02d}/{d.year}",
        f"Customer PO: {inv['po_id'] or '-'}",
        "ITEMS",
    ]
    for ln in inv["lines"]:
        rows.append(f"- {ln['sku']} ; {ln['description']} ; qty={ln['quantity']} ; "
                    f"price=${fmt_thousands(ln['unit_price'])} ; tax={ln['tax_code']} ; "
                    f"line=${fmt_thousands(ln['line_amount'])}")
    rows += [
        f"SUBTOTAL ${fmt_thousands(inv['subtotal_amount'])}",
        f"TAX ${fmt_thousands(inv['tax_amount'])}",
        f"TOTAL {inv['currency']} ${fmt_thousands(inv['total_amount'])}",
    ]
    return "\n".join(rows)


def _layout_c(inv, vendor):
    d = inv["invoice_date"]
    rows = [
        "BEGIN INVOICE",
        f"SUPPLIER_NAME={vendor['vendor_name']}",
        f"SUPPLIER_TAX_ID={vendor['tax_id']}",
        f"DOC_NUMBER={inv['vendor_invoice_number']}",
        f"DOC_DATE={d.day:02d}-{MONTHS[d.month - 1]}-{d.year}",
        f"ORDER_REF={inv['po_id'] or 'NONE'}",
        f"CURRENCY={inv['currency']}",
    ]
    for i, ln in enumerate(inv["lines"], 1):
        rows.append(f"LINE|{i}|{ln['sku']}|{ln['description']}|{ln['quantity']}|"
                    f"{fmt(ln['unit_price'])}|{ln['tax_code']}|{fmt(ln['line_amount'])}")
    rows += [
        f"TOTAL_NET={fmt(inv['subtotal_amount'])}",
        f"TOTAL_TAX={fmt(inv['tax_amount'])}",
        f"TOTAL_GROSS={fmt(inv['total_amount'])}",
        "END INVOICE",
    ]
    return "\n".join(rows)
