# Validation Summary

Overall: **PASS** (90/90 checks passed)

| Category | Check | Status | Failures |
|---|---|---|---|
| schema | vendors: required fields present | PASS | 0 |
| schema | vendors: data types parse | PASS | 0 |
| enums | vendors: allowed values | PASS | 0 |
| ids | vendors: ID/format patterns | PASS | 0 |
| keys | vendors: primary key + unique fields | PASS | 0 |
| schema | purchase_orders: required fields present | PASS | 0 |
| schema | purchase_orders: data types parse | PASS | 0 |
| enums | purchase_orders: allowed values | PASS | 0 |
| ids | purchase_orders: ID/format patterns | PASS | 0 |
| keys | purchase_orders: primary key + unique fields | PASS | 0 |
| schema | purchase_order_lines: required fields present | PASS | 0 |
| schema | purchase_order_lines: data types parse | PASS | 0 |
| enums | purchase_order_lines: allowed values | PASS | 0 |
| ids | purchase_order_lines: ID/format patterns | PASS | 0 |
| keys | purchase_order_lines: primary key + unique fields | PASS | 0 |
| schema | purchase_order_events: required fields present | PASS | 0 |
| schema | purchase_order_events: data types parse | PASS | 0 |
| enums | purchase_order_events: allowed values | PASS | 0 |
| ids | purchase_order_events: ID/format patterns | PASS | 0 |
| keys | purchase_order_events: primary key + unique fields | PASS | 0 |
| schema | goods_receipts: required fields present | PASS | 0 |
| schema | goods_receipts: data types parse | PASS | 0 |
| enums | goods_receipts: allowed values | PASS | 0 |
| ids | goods_receipts: ID/format patterns | PASS | 0 |
| keys | goods_receipts: primary key + unique fields | PASS | 0 |
| schema | goods_receipt_lines: required fields present | PASS | 0 |
| schema | goods_receipt_lines: data types parse | PASS | 0 |
| enums | goods_receipt_lines: allowed values | PASS | 0 |
| ids | goods_receipt_lines: ID/format patterns | PASS | 0 |
| keys | goods_receipt_lines: primary key + unique fields | PASS | 0 |
| schema | invoices: required fields present | PASS | 0 |
| schema | invoices: data types parse | PASS | 0 |
| enums | invoices: allowed values | PASS | 0 |
| ids | invoices: ID/format patterns | PASS | 0 |
| keys | invoices: primary key + unique fields | PASS | 0 |
| schema | invoice_lines: required fields present | PASS | 0 |
| schema | invoice_lines: data types parse | PASS | 0 |
| enums | invoice_lines: allowed values | PASS | 0 |
| ids | invoice_lines: ID/format patterns | PASS | 0 |
| keys | invoice_lines: primary key + unique fields | PASS | 0 |
| schema | approvals: required fields present | PASS | 0 |
| schema | approvals: data types parse | PASS | 0 |
| enums | approvals: allowed values | PASS | 0 |
| ids | approvals: ID/format patterns | PASS | 0 |
| keys | approvals: primary key + unique fields | PASS | 0 |
| schema | payments: required fields present | PASS | 0 |
| schema | payments: data types parse | PASS | 0 |
| enums | payments: allowed values | PASS | 0 |
| ids | payments: ID/format patterns | PASS | 0 |
| keys | payments: primary key + unique fields | PASS | 0 |
| schema | ground_truth: required fields present | PASS | 0 |
| schema | ground_truth: data types parse | PASS | 0 |
| enums | ground_truth: allowed values | PASS | 0 |
| ids | ground_truth: ID/format patterns | PASS | 0 |
| keys | ground_truth: primary key + unique fields | PASS | 0 |
| foreign_keys | purchase_orders.vendor_id -> vendors.vendor_id | PASS | 0 |
| foreign_keys | purchase_order_lines.po_id -> purchase_orders.po_id | PASS | 0 |
| foreign_keys | purchase_order_events.po_id -> purchase_orders.po_id | PASS | 0 |
| foreign_keys | goods_receipts.po_id -> purchase_orders.po_id | PASS | 0 |
| foreign_keys | goods_receipts.vendor_id -> vendors.vendor_id | PASS | 0 |
| foreign_keys | goods_receipt_lines.grn_id -> goods_receipts.grn_id | PASS | 0 |
| foreign_keys | goods_receipt_lines.po_line_id -> purchase_order_lines.po_line_id | PASS | 0 |
| foreign_keys | invoices.vendor_id -> vendors.vendor_id | PASS | 0 |
| foreign_keys | invoices.po_id -> purchase_orders.po_id | PASS | 0 |
| foreign_keys | invoice_lines.invoice_id -> invoices.invoice_id | PASS | 0 |
| foreign_keys | invoice_lines.po_line_id -> purchase_order_lines.po_line_id | PASS | 0 |
| foreign_keys | approvals.invoice_id -> invoices.invoice_id | PASS | 0 |
| foreign_keys | payments.invoice_id -> invoices.invoice_id | PASS | 0 |
| foreign_keys | payments.vendor_id -> vendors.vendor_id | PASS | 0 |
| foreign_keys | ground_truth.invoice_id -> invoices.invoice_id | PASS | 0 |
| foreign_keys | ground_truth.duplicate_of_invoice_id -> invoices.invoice_id | PASS | 0 |
| volume | row counts equal configured volumes | PASS | 0 |
| volume | scenario mix equals target allocation | PASS | 0 |
| structure | every PO has 1-8 lines | PASS | 0 |
| structure | PO line numbers contiguous and SKUs unique per PO | PASS | 0 |
| joins | receipt lines belong to the receipt's PO and vendor | PASS | 0 |
| joins | invoice lines reference PO lines of the invoice's PO; PO vendor = invoice vendor | PASS | 0 |
| ids | invoice IDs embed vendor code; line IDs embed invoice ID | PASS | 0 |
| arithmetic | PO line and header totals reconcile | PASS | 0 |
| arithmetic | invoice line, tax and grand totals reconcile (except labelled defects) | PASS | 0 |
| labels | every TOTAL_MISMATCH label is a real mismatch | PASS | 0 |
| derived | received quantities, receipt status and PO status derived from GRNs | PASS | 0 |
| lifecycle | PO event history follows allowed transitions and ends at current status | PASS | 0 |
| dates | date ordering: onboarding <= PO <= receipt; invoice <= received <= as-of; closures | PASS | 0 |
| duplicates | duplicate vendor invoice numbers exist only as labelled pairs | PASS | 0 |
| ground_truth | one ground-truth row per invoice | PASS | 0 |
| ground_truth | no label columns in input/reference tables | PASS | 0 |
| policy | approvals exist only for eligible invoices and match the approval matrix | PASS | 0 |
| policy | payments only for approved eligible invoices; amounts/dates derived | PASS | 0 |
| joins | every invoice has exactly one raw document | PASS | 0 |
