# Data Dictionary

Generated from `apflow/schema.py` (`python -m apflow docs`). Do not edit by hand.

Conventions: amounts are USD with 2 decimals (half-up rounding); dates are ISO `YYYY-MM-DD`; optional fields are empty strings in CSV and NULL in SQL.

## Relationships

| Table | Primary key | Cardinality |
|---|---|---|
| `vendors` | `vendor_id` | Vendor 1:N PurchaseOrder; Vendor 1:N Invoice |
| `purchase_orders` | `po_id` | PurchaseOrder N:1 Vendor; PurchaseOrder 1:N PurchaseOrderLine (1-8) |
| `purchase_order_lines` | `po_line_id` | PurchaseOrderLine N:1 PurchaseOrder; 1:N GoodsReceiptLine; 1:N InvoiceLine |
| `purchase_order_events` | `event_id` | PurchaseOrder 1:N events |
| `goods_receipts` | `grn_id` | GoodsReceipt N:1 PurchaseOrder; 1:N GoodsReceiptLine |
| `goods_receipt_lines` | `grn_line_id` | GoodsReceiptLine N:1 GoodsReceipt; N:1 PurchaseOrderLine |
| `invoices` | `invoice_id` | Invoice N:1 Vendor; N:0..1 PurchaseOrder (optional); 1:N InvoiceLine; 1:1 Document |
| `invoice_lines` | `invoice_line_id` | InvoiceLine N:1 Invoice; N:0..1 PurchaseOrderLine |
| `approvals` | `approval_id` | Invoice 1:N Approval (one per required level) |
| `payments` | `payment_id` | Invoice 1:0..1 Payment |
| `ground_truth` | `invoice_id` | Invoice 1:1 GroundTruth |

## `vendors`  (input)

Supplier master. Created first; every PO and invoice references it.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `vendor_id` | string | Y | Y | `^VND-\d{5}$` |  |  | Primary key |
| `vendor_code` | string | Y | Y | `^[A-Z]{3}\d{2}$` |  |  | Short code used inside invoice IDs |
| `vendor_name` | string | Y | Y |  |  |  | Legal name (synthetic) |
| `tax_id` | string | Y | Y | `^\d{2}-\d{7}$` |  |  | Synthetic EIN using an unissued IRS prefix |
| `state` | string | Y |  |  |  |  | US state code |
| `categories` | string | Y |  |  |  |  | Pipe-separated catalogue categories supplied |
| `payment_terms` | string | Y |  | NET15, NET30, NET45, NET60 |  |  | Payment terms code |
| `payment_terms_days` | integer | Y |  |  | days |  | Days from invoice date to due date — matches payment_terms |
| `invoice_channel` | string | Y |  | EMAIL, PORTAL, EDI |  |  | How this vendor submits invoices (decides document layout) |
| `payment_method` | string | Y |  | ACH, WIRE, CHECK |  |  | Preferred remittance method |
| `status` | string | Y |  | ACTIVE, CLOSED |  |  | Lifecycle state as of the as-of date |
| `onboarded_date` | date | Y |  |  |  |  | Effective-from date — <= every PO date of the vendor |
| `closed_date` | date | N |  |  |  |  | Effective-to date; required when status=CLOSED — > every PO date; invoices dated after it are VENDOR_INACTIVE |

## `purchase_orders`  (input)

Purchase order header. Totals and status are derived from lines and receipts.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `po_id` | string | Y | Y | `^PO-\d{4}-\d{6}$` |  |  | Primary key |
| `vendor_id` | string | Y |  |  |  | vendors.vendor_id | Supplier |
| `po_date` | date | Y |  |  |  |  | Order date — >= vendor.onboarded_date |
| `requester_id` | string | Y |  | `^REQ-\d{4}$` |  |  | Business requester (role-based synthetic ID) |
| `buyer_id` | string | Y |  | `^BUY-\d{2}$` |  |  | Procurement buyer |
| `cost_center` | string | Y |  | `^CC-\d{4}$` |  |  | Cost centre charged |
| `currency` | string | Y |  | USD |  |  | ISO currency |
| `line_count` | integer | Y |  |  |  |  | Derived: number of lines — 1..8, = count(lines) |
| `subtotal_amount` | decimal | Y |  |  | USD |  | Derived: sum(line_amount) |
| `tax_amount` | decimal | Y |  |  | USD |  | Derived: sum(line tax) |
| `total_amount` | decimal | Y |  |  | USD |  | Derived: subtotal + tax |
| `status` | string | Y |  | CREATED, PARTIALLY_RECEIVED, RECEIVED |  |  | Derived from receipts as of as-of date |

## `purchase_order_lines`  (input)

Ordered items. Receipt quantities are derived from goods receipt lines.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `po_line_id` | string | Y | Y | `^PO-\d{4}-\d{6}-\d{2}$` |  |  | Primary key |
| `po_id` | string | Y |  |  |  | purchase_orders.po_id | Parent PO |
| `line_number` | integer | Y |  |  |  |  | 1..8 — 1..8, unique within PO |
| `sku` | string | Y |  | `^SKU-[A-Z]{3}-\d{4}$` |  |  | Catalogue SKU, unique within a PO |
| `description` | string | Y |  |  |  |  | Item description |
| `uom` | string | Y |  | EA, CS, SEAT, DAY |  |  | Unit of measure |
| `quantity_ordered` | integer | Y |  |  | uom |  | Ordered quantity — > 0 |
| `unit_price` | decimal | Y |  |  | USD |  | Agreed unit price — > 0 |
| `tax_code` | string | Y |  | TX0, TX5, TX8, TX10 |  |  | Tax code |
| `line_amount` | decimal | Y |  |  | USD |  | Derived: quantity_ordered * unit_price |
| `line_tax_amount` | decimal | Y |  |  | USD |  | Derived: round(line_amount * rate, 2) |
| `quantity_received` | integer | Y |  |  | uom |  | Derived: sum of goods receipt lines |
| `receipt_status` | string | Y |  | NOT_RECEIVED, PARTIAL, FULL, OVER |  |  | Derived |

## `purchase_order_events`  (input)

Append-only PO lifecycle history (never overwritten).

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `event_id` | string | Y | Y | `^POE-\d{7}$` |  |  | Primary key |
| `po_id` | string | Y |  |  |  | purchase_orders.po_id | PO |
| `sequence` | integer | Y |  |  |  |  | Order of event within PO |
| `event_date` | date | Y |  |  |  |  | Date of change |
| `from_status` | string | N |  |  |  |  | Previous status |
| `to_status` | string | Y |  | CREATED, PARTIALLY_RECEIVED, RECEIVED |  |  | New status |
| `source_ref` | string | Y |  |  |  |  | PO or GRN that caused the change |

## `goods_receipts`  (input)

Goods receipt (GRN) header.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `grn_id` | string | Y | Y | `^GRN-\d{4}-\d{6}$` |  |  | Primary key |
| `po_id` | string | Y |  |  |  | purchase_orders.po_id | PO received against |
| `vendor_id` | string | Y |  |  |  | vendors.vendor_id | Supplier (denormalised, must equal PO vendor) |
| `receipt_date` | date | Y |  |  |  |  | Posting date — >= po_date, <= as-of date |
| `warehouse` | string | Y |  | WH-EAST, WH-WEST, WH-CENTRAL |  |  | Receiving site |
| `line_count` | integer | Y |  |  |  |  | Derived: number of lines |

## `goods_receipt_lines`  (input)

Quantities received per PO line (full, partial or over-receipt).

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `grn_line_id` | string | Y | Y | `^GRN-\d{4}-\d{6}-\d{2}$` |  |  | Primary key |
| `grn_id` | string | Y |  |  |  | goods_receipts.grn_id | Parent receipt |
| `po_line_id` | string | Y |  |  |  | purchase_order_lines.po_line_id | PO line received — po_line.po_id must equal grn.po_id |
| `quantity_received` | integer | Y |  |  | uom |  | Quantity received — > 0 |

## `invoices`  (reference)

Structured source of each submitted invoice (what the document says). The pipeline never reads this; it is the answer key for extraction accuracy.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `invoice_id` | string | Y | Y | `^INV-[A-Z]{3}\d{2}-\d{4}-\d{6}$` |  |  | Primary key, assigned at intake in received order |
| `document_id` | string | Y | Y | `^DOC-\d{4}-\d{6}$` |  |  | Raw document |
| `vendor_id` | string | Y |  |  |  | vendors.vendor_id | Supplier |
| `po_id` | string | N |  |  |  | purchase_orders.po_id | Referenced PO (blank for non-PO invoices) |
| `vendor_invoice_number` | string | Y |  |  |  |  | Number printed by the vendor (as submitted) |
| `invoice_date` | date | Y |  |  |  |  | Date printed on invoice |
| `received_date` | date | Y |  |  |  |  | Intake date — >= invoice_date, <= as-of date |
| `channel` | string | Y |  | EMAIL, PORTAL, EDI |  |  | Intake channel |
| `currency` | string | Y |  | USD |  |  | ISO currency |
| `line_count` | integer | Y |  |  |  |  | Derived: number of lines |
| `subtotal_amount` | decimal | Y |  |  | USD |  | Derived: sum(line_amount) |
| `tax_amount` | decimal | Y |  |  | USD |  | Derived: sum(line_tax_amount) |
| `total_amount` | decimal | Y |  |  | USD |  | Total stated on document; = subtotal + tax unless labelled TOTAL_MISMATCH |

## `invoice_lines`  (reference)

Invoice lines (answer key for line extraction).

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `invoice_line_id` | string | Y | Y | `^INVL-INV-[A-Z]{3}\d{2}-\d{4}-\d{6}-\d{2}$` |  |  | Primary key |
| `invoice_id` | string | Y |  |  |  | invoices.invoice_id | Parent invoice |
| `line_number` | integer | Y |  |  |  |  | 1..n |
| `po_line_id` | string | N |  |  |  | purchase_order_lines.po_line_id | Matched PO line (blank for non-PO) |
| `sku` | string | Y |  | `^SKU-[A-Z]{3}-\d{4}$` |  |  | SKU |
| `description` | string | Y |  |  |  |  | Description |
| `quantity` | integer | Y |  |  | uom |  | Billed quantity — > 0 |
| `unit_price` | decimal | Y |  |  | USD |  | Billed unit price — > 0 |
| `tax_code` | string | Y |  | TX0, TX5, TX8, TX10 |  |  | Billed tax code |
| `line_amount` | decimal | Y |  |  | USD |  | Derived: quantity * unit_price |
| `line_tax_amount` | decimal | Y |  |  | USD |  | Tax billed; = round(line_amount*rate,2) unless labelled TAX_MISMATCH |

## `approvals`  (reference)

Approval records - created ONLY for eligible (exception-free) invoices, per the approval matrix.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `approval_id` | string | Y | Y | `^APR-\d{4}-\d{6}$` |  |  | Primary key |
| `invoice_id` | string | Y |  |  |  | invoices.invoice_id | Invoice |
| `level` | integer | Y |  |  |  |  | Approval level 1..n |
| `approver_role` | string | Y |  | SYSTEM_AUTO, DEPT_MANAGER, FINANCE_CONTROLLER |  |  | Role |
| `approver_id` | string | Y |  |  |  |  | Role-based approver ID |
| `policy_tier` | integer | Y |  | 1, 2, 3 |  |  | Approval matrix tier applied |
| `decision` | string | Y |  | APPROVED |  |  | Decision |
| `decided_date` | date | Y |  |  |  |  | Decision date — >= invoice.received_date |

## `payments`  (reference)

Payment records - only for approved, eligible invoices.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `payment_id` | string | Y | Y | `^PAY-\d{4}-\d{6}$` |  |  | Primary key |
| `invoice_id` | string | Y | Y |  |  | invoices.invoice_id | Invoice |
| `vendor_id` | string | Y |  |  |  | vendors.vendor_id | Payee |
| `amount` | decimal | Y |  |  | USD |  | Equals invoice total |
| `currency` | string | Y |  | USD |  |  | ISO currency |
| `method` | string | Y |  | ACH, WIRE, CHECK |  |  | Remittance method |
| `due_date` | date | Y |  |  |  |  | invoice_date + payment_terms_days |
| `scheduled_date` | date | Y |  |  |  |  | max(due_date, last approval date) |
| `status` | string | Y |  | SCHEDULED, PAID |  |  | PAID if scheduled_date <= as-of date |
| `paid_date` | date | N |  |  |  |  | Set when PAID |

## `ground_truth`  (ground_truth)

Expected labels and decisions, derived from the injected scenario via the rule table in apflow/policy.py. Kept in a separate folder; never read by the pipeline.

| Field | Type | Req | Unique | Allowed / pattern | Unit | FK | Rule / description |
|---|---|---|---|---|---|---|---|
| `invoice_id` | string | Y | Y |  |  | invoices.invoice_id | Invoice |
| `scenario` | string | Y |  | clean, price_variance, quantity_mismatch, duplicate, missing_receipt, tax_vendor_error |  |  | Scenario family |
| `sub_scenario` | string | Y |  |  |  |  | Edge case |
| `variant` | string | N |  |  |  |  | Variant |
| `issue_type` | string | N |  |  |  |  | Primary injected issue (blank when clean) |
| `target_line` | string | N |  |  |  |  | PO line the anomaly was injected on |
| `injected_detail` | string | N |  |  |  |  | Human-readable description of the injection |
| `duplicate_of_invoice_id` | string | N |  |  |  | invoices.invoice_id | Original invoice for duplicates |
| `expected_exceptions` | string | N |  |  |  |  | Pipe-separated exception codes |
| `expected_primary_exception` | string | N |  | EXTRACTION_FAILED, DUPLICATE_EXACT, DUPLICATE_NUMBER, VENDOR_UNKNOWN, VENDOR_INACTIVE, VENDOR_PO_MISMATCH, TOTAL_MISMATCH, DATE_BEFORE_PO, PO_NOT_FOUND, TAX_MISMATCH, LINE_NOT_ON_PO, MISSING_RECEIPT, QTY_EXCEEDS_PO, QTY_EXCEEDS_RECEIVED, PRICE_VARIANCE |  |  | Primary code by precedence |
| `expected_match_status` | string | Y |  | DUPLICATE, HEADER_ERROR, MATCHED, NON_PO, NO_RECEIPT, PRICE_VARIANCE, QUANTITY_VARIANCE, TAX_VARIANCE, VENDOR_BLOCKED |  |  | Expected match status |
| `expected_route_queue` | string | N |  |  |  |  | Expected work queue |
| `expected_approval_roles` | string | N |  |  |  |  | Pipe-separated roles (eligible invoices only) |
| `expected_payment_ready` | boolean | Y |  | true, false |  |  | True only for eligible invoices |

