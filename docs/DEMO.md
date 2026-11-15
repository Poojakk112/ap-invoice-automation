# Two-minute demo

1. **Run it** (30 s)
   ```powershell
   cd backend
   python -m pytest -q          # 67 passed
   python -m apflow all         # generate, validate, run, evaluate, what-if, robustness, impact, reproduce
   python -m uvicorn api:app    # open http://127.0.0.1:8000
   ```
2. **Show the headline** (20 s): 2,000 invoices, 70% touchless, safety gate "0 · PASS", 90/90 validation checks.
3. **Show one blocked invoice** (30 s): click `INV-UNI09-2026-000003`. Read the "Why" line (price +14.53% vs 2%
   tolerance), the audit trail, and the original document.
4. **Show the trade-off** (20 s): scroll to the what-if table. Say: "at 0% good invoices get blocked, at 10%
   overcharge leaks. The business picks the number."
5. **Show the honesty** (20 s): scroll to the robustness table. Say: "I damaged 900 documents. It found a real hole:
   a blank PO number skipped the 3-way match. I fixed it, and a test now prevents it coming back."

Command-line version of step 3: `python -m apflow explain INV-UNI09-2026-000003`
