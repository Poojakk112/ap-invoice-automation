# Design decisions

Short notes on why the project is built this way. Edit these in your own words.

1. **Duplicate check comes first.** A duplicate must not use up PO quantity or receipts, otherwise it could hide a
   real over-billing on the next invoice.
2. **Quantities are checked cumulatively across invoices.** A PO billed in two invoices of 6 + 6 against an order
   of 10 must be caught, even though each invoice alone looks fine.
3. **Labels come from rules, not randomness.** The generator records which problem it injected, and the expected
   outcome is derived from one rule table. This keeps the ground truth consistent with the policy.
4. **The pipeline never reads the answers.** `input/` holds only what a real system would receive. `reference/`
   and `ground_truth/` are used only for scoring.
5. **A blocked invoice cannot become payable.** The release step raises an error if anything tries it, so the
   control does not depend on every code path being correct.
6. **Policy lives in a settings file.** Tolerances, tax codes and approval limits are in `policy.json`, so a
   process owner can change them without touching code.
7. **Failures are loud.** An unreadable document or item line becomes an exception for a person. It is never
   guessed or dropped.
8. **I tested the system by damaging it.** The robustness test found that a blank PO number skipped the 3-way
   match. That is now blocked, with a test to keep it fixed.
9. **Impact numbers are marked as assumptions.** Measured and assumed values are labelled separately.
