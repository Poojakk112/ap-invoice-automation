# Robustness test

Damaged documents are generated from the clean ones with a fixed seed. The key number is **unsafe payments**: damage must never turn into a wrong payment.

**900 damaged documents, 0 unsafe payments.**

| Damage | Docs | Handled OK | Safely blocked | Still blocked | Unsafe | Caught by |
|---|---|---|---|---|---|---|
| One digit in an item line amount is wrong (OCR misread) | 150 | 0 | 97 | 53 | **0** | DUPLICATE_EXACT (6), DUPLICATE_NUMBER (7), TOTAL_MISMATCH (137) |
| One digit in the invoice total is wrong | 150 | 0 | 100 | 50 | **0** | DUPLICATE_NUMBER (9), TOTAL_MISMATCH (138), VENDOR_INACTIVE (3) |
| A digit in an item amount is read as a letter (O for 0, l for 1, ...) | 150 | 0 | 150 | 0 | **0** | EXTRACTION_FAILED (150) |
| The total line is missing (page cut off) | 150 | 0 | 150 | 0 | **0** | EXTRACTION_FAILED (150) |
| The PO number is blank or unreadable | 150 | 0 | 100 | 50 | **0** | DUPLICATE_EXACT (3), DUPLICATE_NUMBER (3), PO_REQUIRED (142), VENDOR_INACTIVE (2) |
| Windows line endings and trailing spaces | 150 | 99 | 0 | 51 | **0** | DATE_BEFORE_PO (2), DUPLICATE_EXACT (5), DUPLICATE_NUMBER (3), MISSING_RECEIPT (6), PRICE_VARIANCE (20), QTY_EXCEEDS_PO (6), QTY_EXCEEDS_RECEIVED (7), TAX_MISMATCH (1), TOTAL_MISMATCH (1) |

*Safely blocked* means a good invoice was stopped and routed to a person, which costs review time but pays nothing wrongly. *Unsafe* means money would have moved incorrectly.
