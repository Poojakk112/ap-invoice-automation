# What-if: price tolerance

Stricter tolerance: more good invoices need a person. Looser tolerance: more overcharge is paid. 'Good invoices blocked' counts invoices the ground truth marks payable that were stopped. Note: the synthetic price variances are either under 1.5% or over 3%, so 2% and 3% give identical results; real data would be smoother.

| Tolerance | Touchless | Need a person | Good invoices blocked | Variances missed | Overcharge paid | Overcharge stopped |
|---|---|---|---|---|---|---|
| 0% | 64.5% | 71 | 11 | 0 | $0.00 | $19,880.49 |
| 1% | 69.0% | 62 | 2 | 0 | $333.22 | $19,547.27 |
| 2% (current) | 70.0% | 60 | 0 | 0 | $410.65 | $19,469.84 |
| 3% | 70.0% | 60 | 0 | 0 | $410.65 | $19,469.84 |
| 5% | 70.5% | 59 | 0 | 1 | $467.26 | $19,413.23 |
| 10% | 73.0% | 54 | 0 | 6 | $1,218.72 | $18,661.77 |
