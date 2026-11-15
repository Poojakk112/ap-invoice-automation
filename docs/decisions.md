# Design decisions

Short notes on why I built the project this way, in my own words.

1. **I check duplicates first.** A duplicate should not use up the PO quantity or the receipts. If it did, a real over-billing on the next invoice could be missed.
2. **I count quantities across all invoices of a PO.** A PO for 10 units billed as 6 + 6 looks fine one invoice at a time, but it is over-billing.
3. **Expected results come from rules, not luck.** The generator remembers which mistake it added, and the correct outcome comes from one rule table.
4. **The pipeline never sees the answers.** It only reads the input folder. The answers are used afterwards, only to score it.
5. **A blocked invoice can never become payable.** The code raises an error if anything tries, so safety does not depend on every other line being right.
6. **Rules live in a settings file.** A business owner can change a tolerance or an approval limit without touching code.
7. **Failures are loud.** If a document or a line cannot be read, a person gets an exception. The system never guesses.
8. **I tested the system by damaging it.** The test found that a blank PO number skipped the 3-way match. It is now blocked, and a test keeps it fixed.
9. **Impact numbers are labelled.** Measured values and assumptions are shown separately.
