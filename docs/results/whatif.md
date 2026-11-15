# What-if: price tolerance

Stricter tolerance: more good invoices need a person. Looser tolerance: more overcharge is paid. 'Good invoices blocked' counts invoices the ground truth marks payable that were stopped. Note: the synthetic price variances are either under 1.5% or over 3%, so 2% and 3% give identical results; real data would be smoother.

| Tolerance | Touchless | Need a person | Good invoices blocked | Variances missed | Overcharge paid | Overcharge stopped |
|---|---|---|---|---|---|---|
| 0% | 64.4% | 712 | 112 | 0 | $0.00 | $195,118.73 |
| 1% | 68.0% | 641 | 41 | 0 | $3,056.54 | $192,062.19 |
| 2% (current) | 70.0% | 600 | 0 | 0 | $8,083.30 | $187,035.43 |
| 3% | 70.0% | 600 | 0 | 0 | $8,083.30 | $187,035.43 |
| 5% | 70.9% | 583 | 0 | 17 | $14,855.83 | $180,262.90 |
| 10% | 73.2% | 536 | 0 | 64 | $38,833.95 | $156,284.78 |
