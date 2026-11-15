# Business impact estimate (starter dataset)

Dollar and hour figures mix **measured** results with **assumptions**. The assumptions are in `backend/config/assumptions.json` and must be replaced with the customer's own numbers. Duplicate and over-billing values come from synthetic data, so they show how the control works, not what a real company would save.

| Item | Value | Basis |
|---|---|---|
| Invoices processed | 200 | measured |
| Touchless (no manual matching) | 140 (70%) | measured |
| Invoices needing a person | 60 | measured |
| Manual effort before (hours) | 52 | assumption x measured volume |
| Effort with automation (hours) | 14 | assumption x measured volume |
| Hours saved | 37 | derived |
| Full-time equivalents freed | 0.02 | derived |
| Labour cost saved | $1,307 | derived (assumed hourly cost) |
| Duplicate invoices blocked (value) | $39,894 | measured on synthetic data |
| Over-billing blocked (value) | $37,549 | measured on synthetic data |
| Expected leakage avoided vs manual process | $23,233 | assumption: share a manual process would miss |

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
