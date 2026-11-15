"""Single source of truth for every table: fields, types, keys and rules.

Used to (1) validate generated data, (2) create SQLite / MariaDB DDL and
(3) render docs/data_dictionary.md. Change a rule here and all three follow.
"""

from dataclasses import dataclass

from apflow.ids import PATTERNS
from apflow.policy import EXCEPTIONS, MATCH_STATUSES

TAX_CODES = ("TX0", "TX5", "TX8", "TX10")
UOMS = ("EA", "CS", "SEAT", "DAY")


@dataclass(frozen=True)
class Field:
    name: str
    type: str                  # string | integer | decimal | date | boolean | text
    description: str
    required: bool = True
    allowed: tuple = ()
    unit: str = ""
    unique: bool = False
    pattern: str = ""
    fk: str = ""               # "table.column"
    rule: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    group: str                 # input | reference | ground_truth
    description: str
    pk: str
    cardinality: str
    fields: tuple

    def field(self, name):
        return next(f for f in self.fields if f.name == name)

    @property
    def columns(self):
        return [f.name for f in self.fields]


F = Field

VENDORS = Table(
    "vendors", "input", "Supplier master. Created first; every PO and invoice references it.",
    "vendor_id", "Vendor 1:N PurchaseOrder; Vendor 1:N Invoice",
    (
        F("vendor_id", "string", "Primary key", unique=True, pattern=PATTERNS["vendor_id"]),
        F("vendor_code", "string", "Short code used inside invoice IDs", unique=True, pattern=PATTERNS["vendor_code"]),
        F("vendor_name", "string", "Legal name (synthetic)", unique=True),
        F("tax_id", "string", "Synthetic EIN using an unissued IRS prefix", unique=True, pattern=r"^\d{2}-\d{7}$"),
        F("state", "string", "US state code"),
        F("categories", "string", "Pipe-separated catalogue categories supplied"),
        F("payment_terms", "string", "Payment terms code", allowed=("NET15", "NET30", "NET45", "NET60")),
        F("payment_terms_days", "integer", "Days from invoice date to due date", unit="days", rule="matches payment_terms"),
        F("invoice_channel", "string", "How this vendor submits invoices (decides document layout)", allowed=("EMAIL", "PORTAL", "EDI")),
        F("payment_method", "string", "Preferred remittance method", allowed=("ACH", "WIRE", "CHECK")),
        F("status", "string", "Lifecycle state as of the as-of date", allowed=("ACTIVE", "CLOSED")),
        F("onboarded_date", "date", "Effective-from date", rule="<= every PO date of the vendor"),
        F("closed_date", "date", "Effective-to date; required when status=CLOSED", required=False,
          rule="> every PO date; invoices dated after it are VENDOR_INACTIVE"),
    ),
)

PURCHASE_ORDERS = Table(
    "purchase_orders", "input", "Purchase order header. Totals and status are derived from lines and receipts.",
    "po_id", "PurchaseOrder N:1 Vendor; PurchaseOrder 1:N PurchaseOrderLine (1-8)",
    (
        F("po_id", "string", "Primary key", unique=True, pattern=PATTERNS["po_id"]),
        F("vendor_id", "string", "Supplier", fk="vendors.vendor_id"),
        F("po_date", "date", "Order date", rule=">= vendor.onboarded_date"),
        F("requester_id", "string", "Business requester (role-based synthetic ID)", pattern=r"^REQ-\d{4}$"),
        F("buyer_id", "string", "Procurement buyer", pattern=r"^BUY-\d{2}$"),
        F("cost_center", "string", "Cost centre charged", pattern=r"^CC-\d{4}$"),
        F("currency", "string", "ISO currency", allowed=("USD",)),
        F("line_count", "integer", "Derived: number of lines", rule="1..8, = count(lines)"),
        F("subtotal_amount", "decimal", "Derived: sum(line_amount)", unit="USD"),
        F("tax_amount", "decimal", "Derived: sum(line tax)", unit="USD"),
        F("total_amount", "decimal", "Derived: subtotal + tax", unit="USD"),
        F("status", "string", "Derived from receipts as of as-of date",
          allowed=("CREATED", "PARTIALLY_RECEIVED", "RECEIVED")),
    ),
)

PO_LINES = Table(
    "purchase_order_lines", "input", "Ordered items. Receipt quantities are derived from goods receipt lines.",
    "po_line_id", "PurchaseOrderLine N:1 PurchaseOrder; 1:N GoodsReceiptLine; 1:N InvoiceLine",
    (
        F("po_line_id", "string", "Primary key", unique=True, pattern=PATTERNS["po_line_id"]),
        F("po_id", "string", "Parent PO", fk="purchase_orders.po_id"),
        F("line_number", "integer", "1..8", rule="1..8, unique within PO"),
        F("sku", "string", "Catalogue SKU, unique within a PO", pattern=r"^SKU-[A-Z]{3}-\d{4}$"),
        F("description", "string", "Item description"),
        F("uom", "string", "Unit of measure", allowed=UOMS),
        F("quantity_ordered", "integer", "Ordered quantity", unit="uom", rule="> 0"),
        F("unit_price", "decimal", "Agreed unit price", unit="USD", rule="> 0"),
        F("tax_code", "string", "Tax code", allowed=TAX_CODES),
        F("line_amount", "decimal", "Derived: quantity_ordered * unit_price", unit="USD"),
        F("line_tax_amount", "decimal", "Derived: round(line_amount * rate, 2)", unit="USD"),
        F("quantity_received", "integer", "Derived: sum of goods receipt lines", unit="uom"),
        F("receipt_status", "string", "Derived", allowed=("NOT_RECEIVED", "PARTIAL", "FULL", "OVER")),
    ),
)

PO_EVENTS = Table(
    "purchase_order_events", "input", "Append-only PO lifecycle history (never overwritten).",
    "event_id", "PurchaseOrder 1:N events",
    (
        F("event_id", "string", "Primary key", unique=True, pattern=r"^POE-\d{7}$"),
        F("po_id", "string", "PO", fk="purchase_orders.po_id"),
        F("sequence", "integer", "Order of event within PO"),
        F("event_date", "date", "Date of change"),
        F("from_status", "string", "Previous status", required=False),
        F("to_status", "string", "New status", allowed=("CREATED", "PARTIALLY_RECEIVED", "RECEIVED")),
        F("source_ref", "string", "PO or GRN that caused the change"),
    ),
)

GOODS_RECEIPTS = Table(
    "goods_receipts", "input", "Goods receipt (GRN) header.",
    "grn_id", "GoodsReceipt N:1 PurchaseOrder; 1:N GoodsReceiptLine",
    (
        F("grn_id", "string", "Primary key", unique=True, pattern=PATTERNS["grn_id"]),
        F("po_id", "string", "PO received against", fk="purchase_orders.po_id"),
        F("vendor_id", "string", "Supplier (denormalised, must equal PO vendor)", fk="vendors.vendor_id"),
        F("receipt_date", "date", "Posting date", rule=">= po_date, <= as-of date"),
        F("warehouse", "string", "Receiving site", allowed=("WH-EAST", "WH-WEST", "WH-CENTRAL")),
        F("line_count", "integer", "Derived: number of lines"),
    ),
)

GRN_LINES = Table(
    "goods_receipt_lines", "input", "Quantities received per PO line (full, partial or over-receipt).",
    "grn_line_id", "GoodsReceiptLine N:1 GoodsReceipt; N:1 PurchaseOrderLine",
    (
        F("grn_line_id", "string", "Primary key", unique=True, pattern=PATTERNS["grn_line_id"]),
        F("grn_id", "string", "Parent receipt", fk="goods_receipts.grn_id"),
        F("po_line_id", "string", "PO line received", fk="purchase_order_lines.po_line_id",
          rule="po_line.po_id must equal grn.po_id"),
        F("quantity_received", "integer", "Quantity received", unit="uom", rule="> 0"),
    ),
)

INVOICES = Table(
    "invoices", "reference",
    "Structured source of each submitted invoice (what the document says). The pipeline never reads this; "
    "it is the answer key for extraction accuracy.",
    "invoice_id", "Invoice N:1 Vendor; N:0..1 PurchaseOrder (optional); 1:N InvoiceLine; 1:1 Document",
    (
        F("invoice_id", "string", "Primary key, assigned at intake in received order", unique=True, pattern=PATTERNS["invoice_id"]),
        F("document_id", "string", "Raw document", unique=True, pattern=PATTERNS["document_id"]),
        F("vendor_id", "string", "Supplier", fk="vendors.vendor_id"),
        F("po_id", "string", "Referenced PO (blank for non-PO invoices)", required=False, fk="purchase_orders.po_id"),
        F("vendor_invoice_number", "string", "Number printed by the vendor (as submitted)"),
        F("invoice_date", "date", "Date printed on invoice"),
        F("received_date", "date", "Intake date", rule=">= invoice_date, <= as-of date"),
        F("channel", "string", "Intake channel", allowed=("EMAIL", "PORTAL", "EDI")),
        F("currency", "string", "ISO currency", allowed=("USD",)),
        F("line_count", "integer", "Derived: number of lines"),
        F("subtotal_amount", "decimal", "Derived: sum(line_amount)", unit="USD"),
        F("tax_amount", "decimal", "Derived: sum(line_tax_amount)", unit="USD"),
        F("total_amount", "decimal", "Total stated on document; = subtotal + tax unless labelled TOTAL_MISMATCH", unit="USD"),
    ),
)

INVOICE_LINES = Table(
    "invoice_lines", "reference", "Invoice lines (answer key for line extraction).",
    "invoice_line_id", "InvoiceLine N:1 Invoice; N:0..1 PurchaseOrderLine",
    (
        F("invoice_line_id", "string", "Primary key", unique=True, pattern=PATTERNS["invoice_line_id"]),
        F("invoice_id", "string", "Parent invoice", fk="invoices.invoice_id"),
        F("line_number", "integer", "1..n"),
        F("po_line_id", "string", "Matched PO line (blank for non-PO)", required=False, fk="purchase_order_lines.po_line_id"),
        F("sku", "string", "SKU", pattern=r"^SKU-[A-Z]{3}-\d{4}$"),
        F("description", "string", "Description"),
        F("quantity", "integer", "Billed quantity", unit="uom", rule="> 0"),
        F("unit_price", "decimal", "Billed unit price", unit="USD", rule="> 0"),
        F("tax_code", "string", "Billed tax code", allowed=TAX_CODES),
        F("line_amount", "decimal", "Derived: quantity * unit_price", unit="USD"),
        F("line_tax_amount", "decimal", "Tax billed; = round(line_amount*rate,2) unless labelled TAX_MISMATCH", unit="USD"),
    ),
)

APPROVALS = Table(
    "approvals", "reference",
    "Approval records - created ONLY for eligible (exception-free) invoices, per the approval matrix.",
    "approval_id", "Invoice 1:N Approval (one per required level)",
    (
        F("approval_id", "string", "Primary key", unique=True, pattern=PATTERNS["approval_id"]),
        F("invoice_id", "string", "Invoice", fk="invoices.invoice_id"),
        F("level", "integer", "Approval level 1..n"),
        F("approver_role", "string", "Role", allowed=("SYSTEM_AUTO", "DEPT_MANAGER", "FINANCE_CONTROLLER")),
        F("approver_id", "string", "Role-based approver ID"),
        F("policy_tier", "integer", "Approval matrix tier applied", allowed=(1, 2, 3)),
        F("decision", "string", "Decision", allowed=("APPROVED",)),
        F("decided_date", "date", "Decision date", rule=">= invoice.received_date"),
    ),
)

PAYMENTS = Table(
    "payments", "reference", "Payment records - only for approved, eligible invoices.",
    "payment_id", "Invoice 1:0..1 Payment",
    (
        F("payment_id", "string", "Primary key", unique=True, pattern=PATTERNS["payment_id"]),
        F("invoice_id", "string", "Invoice", unique=True, fk="invoices.invoice_id"),
        F("vendor_id", "string", "Payee", fk="vendors.vendor_id"),
        F("amount", "decimal", "Equals invoice total", unit="USD"),
        F("currency", "string", "ISO currency", allowed=("USD",)),
        F("method", "string", "Remittance method", allowed=("ACH", "WIRE", "CHECK")),
        F("due_date", "date", "invoice_date + payment_terms_days"),
        F("scheduled_date", "date", "max(due_date, last approval date)"),
        F("status", "string", "PAID if scheduled_date <= as-of date", allowed=("SCHEDULED", "PAID")),
        F("paid_date", "date", "Set when PAID", required=False),
    ),
)

GROUND_TRUTH = Table(
    "ground_truth", "ground_truth",
    "Expected labels and decisions, derived from the injected scenario via the rule table in apflow/policy.py. "
    "Kept in a separate folder; never read by the pipeline.",
    "invoice_id", "Invoice 1:1 GroundTruth",
    (
        F("invoice_id", "string", "Invoice", unique=True, fk="invoices.invoice_id"),
        F("scenario", "string", "Scenario family",
          allowed=("clean", "price_variance", "quantity_mismatch", "duplicate", "missing_receipt", "tax_vendor_error")),
        F("sub_scenario", "string", "Edge case"),
        F("variant", "string", "Variant", required=False),
        F("issue_type", "string", "Primary injected issue (blank when clean)", required=False),
        F("target_line", "string", "PO line the anomaly was injected on", required=False),
        F("injected_detail", "string", "Human-readable description of the injection", required=False),
        F("duplicate_of_invoice_id", "string", "Original invoice for duplicates", required=False, fk="invoices.invoice_id"),
        F("expected_exceptions", "string", "Pipe-separated exception codes", required=False),
        F("expected_primary_exception", "string", "Primary code by precedence", required=False,
          allowed=tuple([""] + list(EXCEPTIONS))),
        F("expected_match_status", "string", "Expected match status", allowed=tuple(MATCH_STATUSES)),
        F("expected_route_queue", "string", "Expected work queue", required=False),
        F("expected_approval_roles", "string", "Pipe-separated roles (eligible invoices only)", required=False),
        F("expected_payment_ready", "boolean", "True only for eligible invoices", allowed=("true", "false")),
    ),
)

INPUT_TABLES = [VENDORS, PURCHASE_ORDERS, PO_LINES, PO_EVENTS, GOODS_RECEIPTS, GRN_LINES]
REFERENCE_TABLES = [INVOICES, INVOICE_LINES, APPROVALS, PAYMENTS]
ALL_TABLES = INPUT_TABLES + REFERENCE_TABLES + [GROUND_TRUTH]
TABLES = {t.name: t for t in ALL_TABLES}


# ---------------------------------------------------------------- DDL ----
def _sql_type(f: Field, dialect: str) -> str:
    if f.type == "integer":
        return "INTEGER" if dialect == "sqlite" else "INT"
    if f.type == "decimal":
        return "NUMERIC(14,2)" if dialect == "sqlite" else "DECIMAL(14,2)"
    if f.type == "date":
        return "TEXT" if dialect == "sqlite" else "DATE"
    if f.type == "boolean":
        return "TEXT" if dialect == "sqlite" else "VARCHAR(5)"
    if f.type == "text":
        return "TEXT"
    return "TEXT" if dialect == "sqlite" else "VARCHAR(255)"


def ddl(table: Table, dialect: str = "mariadb") -> str:
    lines = []
    for f in table.fields:
        col = f"  {f.name} {_sql_type(f, dialect)}"
        if f.required:
            col += " NOT NULL"
        lines.append(col)
    lines.append(f"  PRIMARY KEY ({table.pk})")
    for f in table.fields:
        if f.unique and f.name != table.pk:
            lines.append(f"  UNIQUE ({f.name})")
    for f in table.fields:
        if f.fk:
            ref_t, ref_c = f.fk.split(".")
            lines.append(f"  FOREIGN KEY ({f.name}) REFERENCES {ref_t}({ref_c})")
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if dialect == "mariadb" else ""
    return f"CREATE TABLE {table.name} (\n" + ",\n".join(lines) + f"\n){suffix};"


def data_dictionary_markdown() -> str:
    out = ["# Data Dictionary", "",
           "Generated from `apflow/schema.py` (`python -m apflow docs`). Do not edit by hand.", "",
           "Conventions: amounts are USD with 2 decimals (half-up rounding); dates are ISO `YYYY-MM-DD`; "
           "optional fields are empty strings in CSV and NULL in SQL.", ""]
    out += ["## Relationships", "", "| Table | Primary key | Cardinality |", "|---|---|---|"]
    for t in ALL_TABLES:
        out.append(f"| `{t.name}` | `{t.pk}` | {t.cardinality} |")
    out.append("")
    for t in ALL_TABLES:
        out += [f"## `{t.name}`  ({t.group})", "", t.description, "",
                "| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |",
                "|---|---|---|---|---|---|---|---|"]
        for f in t.fields:
            allowed = ", ".join(str(a) for a in f.allowed if a != "") if f.allowed else (f"`{f.pattern}`" if f.pattern else "")
            rule = f.description + (f" — {f.rule}" if f.rule else "")
            out.append(f"| `{f.name}` | {f.type} | {'Y' if f.required else 'N'} | {'Y' if f.unique else ''} | "
                       f"{allowed} | {f.unit} | {f.fk} | {rule} |")
        out.append("")
    return "\n".join(out)
