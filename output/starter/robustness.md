# Robustness test

Damaged documents are generated from the clean ones with a fixed seed. The key number is **unsafe payments**: damage must never turn into a wrong payment.

**900 damaged documents, 0 unsafe payments.**

| Damage | Docs | Handled OK | Safely blocked | Still blocked | Unsafe | Caught by |
|---|---|---|---|---|---|---|
| One digit in an item line amount is wrong (OCR misread) | 150 | 0 | 103 | 47 | **0** | DUPLICATE_EXACT (5), DUPLICATE_NUMBER (4), TOTAL_MISMATCH (139), VENDOR_INACTIVE (2) |
| One digit in the invoice total is wrong | 150 | 0 | 102 | 48 | **0** | DUPLICATE_EXACT (1), DUPLICATE_NUMBER (7), TOTAL_MISMATCH (140), VENDOR_INACTIVE (2) |
| A digit in an item amount is read as a letter (O for 0, l for 1, ...) | 150 | 0 | 150 | 0 | **0** | EXTRACTION_FAILED (150) |
| The total line is missing (page cut off) | 150 | 0 | 150 | 0 | **0** | EXTRACTION_FAILED (150) |
| The PO number is blank or unreadable | 150 | 0 | 103 | 47 | **0** | DUPLICATE_EXACT (5), DUPLICATE_NUMBER (2), PO_REQUIRED (141), VENDOR_INACTIVE (2) |
| Windows line endings and trailing spaces | 150 | 108 | 0 | 42 | **0** | DATE_BEFORE_PO (1), DUPLICATE_EXACT (4), DUPLICATE_NUMBER (1), MISSING_RECEIPT (7), PRICE_VARIANCE (12), QTY_EXCEEDS_PO (3), QTY_EXCEEDS_RECEIVED (9), TAX_MISMATCH (2), TOTAL_MISMATCH (1), VENDOR_INACTIVE (2) |

*Safely blocked* means a good invoice was stopped and routed to a person, which costs review time but pays nothing wrongly. *Unsafe* means money would have moved incorrectly.
