# Business impact estimate (full dataset)

Dollar and hour figures mix **measured** results with **assumptions**. The assumptions are in `backend/config/assumptions.json` and must be replaced with the customer's own numbers. Duplicate and over-billing values come from synthetic data, so they show how the control works, not what a real company would save.

| Item | Value | Basis |
|---|---|---|
| Invoices processed | 2,000 | measured |
| Touchless (no manual matching) | 1,400 (70%) | measured |
| Invoices needing a person | 600 | measured |
| Manual effort before (hours) | 517 | assumption x measured volume |
| Effort with automation (hours) | 143 | assumption x measured volume |
| Hours saved | 373 | derived |
| Full-time equivalents freed | 0.21 | derived |
| Labour cost saved | $13,067 | derived (assumed hourly cost) |
| Duplicate invoices blocked (value) | $573,940 | measured on synthetic data |
| Over-billing blocked (value) | $478,314 | measured on synthetic data |
| Expected leakage avoided vs manual process | $315,676 | assumption: share a manual process would miss |

## Assumptions used

| Assumption | Value |
|---|---|
| minutes per invoice manual processing | 8 |
| minutes per exception manual investigation | 25 |
| minutes per invoice touchless spot check | 1 |
| minutes per exception with guided reason | 12 |
| loaded cost per hour usd | 35 |
| working hours per fte year | 1800 |
| manual process miss rate duplicates | 0.3 |
| manual process miss rate overbilling | 0.3 |
