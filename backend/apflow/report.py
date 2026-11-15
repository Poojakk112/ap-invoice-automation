"""Static HTML run report for the process owner / operations analyst.

No JavaScript or external assets: open output/<dataset>/report.html in any browser.
"""

import html
from pathlib import Path

from apflow.export import read_csv


def _pct(x):
    return f"{float(x) * 100:.1f}%"


def _money(x):
    return f"${float(x):,.2f}"


def _bar(value, max_value):
    w = 0 if not max_value else max(2, int(240 * value / max_value))
    return f'<span class="bar" style="width:{w}px"></span>'


def build_report(metrics: dict, validation: dict, out_dir, dataset_name: str, manifest: dict) -> Path:
    out_dir = Path(out_dir)
    k, acc, safety = metrics["kpis"], metrics["acceptance"], metrics["safety"]
    esc = html.escape
    cards = [
        ("Invoices processed", f"{k['invoices_processed']:,}"),
        ("Straight-through (touchless)", _pct(k["straight_through_rate"])),
        ("Payment-ready value", _money(k["payment_ready_value"])),
        ("Duplicate payments prevented", _money(k["duplicate_payments_prevented_value"])),
        ("Over-billing stopped", _money(k["overbilling_prevented_value"])),
        ("Acceptance (all 5 criteria)", _pct(acc["all"])),
        ("Blocked but payment-ready", f"{safety['blocked_invoices_marked_payment_ready']} ({safety['gate']})"),
        ("Data validation", f"{validation['checks_total'] - validation['checks_failed']}/{validation['checks_total']} checks"),
    ]
    q = k["exceptions_by_queue"]
    qmax = max(q.values()) if q else 0
    queue_rows = "".join(f"<tr><td>{esc(name)}</td><td>{n}</td><td>{_bar(n, qmax)}</td></tr>" for name, n in
                         sorted(q.items(), key=lambda x: -x[1]))
    det_rows = "".join(
        f"<tr><td>{esc(c)}</td><td>{v['support']}</td><td>{v['tp']}</td><td>{v['fp']}</td><td>{v['fn']}</td>"
        f"<td>{_pct(v['precision'])}</td><td>{_pct(v['recall'])}</td><td>{_pct(v['f1'])}</td></tr>"
        for c, v in metrics["exception_detection"].items())
    acc_rows = "".join(f"<tr><td>{esc(name)}</td><td>{_pct(v)}</td></tr>" for name, v in acc.items())
    ext_rows = "".join(f"<tr><td>{esc(f)}</td><td>{_pct(v)}</td></tr>" for f, v in metrics["extraction_field_accuracy"].items())
    risk_rows = "".join(f"<tr><td>{esc(c)}</td><td>{_money(v)}</td></tr>" for c, v in k["value_at_risk_by_code"].items())
    vend_rows = "".join(f"<tr><td>{esc(v['vendor_id'])}</td><td>{esc(v['vendor_name'])}</td><td>{v['exceptions']}</td></tr>"
                        for v in k["top_exception_vendors"])
    val_rows = "".join(f"<tr class='{c['status'].lower()}'><td>{esc(c['category'])}</td><td>{esc(c['check'])}</td>"
                       f"<td>{c['status']}</td><td>{c['failures']}</td></tr>" for c in validation["checks"])
    samples = [d for d in read_csv(out_dir / "decisions.csv") if d["exceptions"]]
    seen, picked = set(), []
    for d in samples:
        if d["primary_exception"] not in seen:
            seen.add(d["primary_exception"])
            picked.append(d)
    sample_rows = "".join(f"<tr><td>{esc(d['invoice_id'])}</td><td>{esc(d['route_queue'])}</td>"
                          f"<td>{esc(d['explanation'])}</td></tr>" for d in picked)

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AP Automation Run Report</title>
<style>
:root {{ --bg:#f7f7f5; --card:#fff; --ink:#1d2433; --muted:#5b6475; --line:#e3e5ea; --accent:#2457c5; --ok:#1d7a46; --bad:#b42318; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171d; --card:#1d2129; --ink:#e8eaee; --muted:#9aa3b2; --line:#2c323d; --accent:#7aa2ff; --ok:#4cc38a; --bad:#ff7a6e; }} }}
body {{ margin:0; font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--ink); }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:32px 0 8px; }}
.muted {{ color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-top:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }}
.card b {{ display:block; font-size:20px; margin-top:4px; font-variant-numeric:tabular-nums; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
th,td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; font-variant-numeric:tabular-nums; }}
th {{ font-weight:600; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.03em; }}
.bar {{ display:inline-block; height:10px; background:var(--accent); border-radius:2px; }}
tr.fail td {{ color:var(--bad); }} tr.pass td:nth-child(3) {{ color:var(--ok); }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }}
.scroll {{ overflow-x:auto; }}
</style></head><body><main>
<h1>AP Invoice Automation: Run Report</h1>
<div class="muted">Dataset <b>{esc(dataset_name)}</b> · seed {manifest.get('seed')} · scale {manifest.get('scale')} · as-of {manifest.get('as_of_date')}</div>
<div class="cards">{''.join(f'<div class="card"><span class="muted">{esc(a)}</span><b>{esc(b)}</b></div>' for a, b in cards)}</div>

<h2>Acceptance criteria (share of invoices passing)</h2>
<div class="grid2"><table><tr><th>Criterion</th><th>Pass rate</th></tr>{acc_rows}</table>
<table><tr><th>Work queue</th><th>Invoices</th><th></th></tr>{queue_rows}</table></div>

<h2>Exception detection vs ground truth</h2>
<div class="scroll"><table><tr><th>Code</th><th>Support</th><th>TP</th><th>FP</th><th>FN</th><th>Precision</th><th>Recall</th><th>F1</th></tr>{det_rows}</table></div>

<h2>Why invoices were blocked (one example per exception type)</h2>
<div class="scroll"><table><tr><th>Invoice</th><th>Queue</th><th>Explanation</th></tr>{sample_rows}</table></div>

<h2>Value at risk and vendors to review</h2>
<div class="grid2"><table><tr><th>Exception</th><th>Value at risk</th></tr>{risk_rows}</table>
<table><tr><th>Vendor</th><th>Name</th><th>Exceptions</th></tr>{vend_rows}</table></div>

<h2>Extraction accuracy by field</h2>
<table><tr><th>Field</th><th>Accuracy</th></tr>{ext_rows}</table>

<h2>Data validation</h2>
<div class="scroll"><table><tr><th>Category</th><th>Check</th><th>Status</th><th>Failures</th></tr>{val_rows}</table></div>
</main></body></html>
"""
    path = out_dir / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
