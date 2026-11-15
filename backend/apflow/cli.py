"""Command line interface.

    python -m apflow all --scale 0.1 --name starter     # everything, small dataset
    python -m apflow all                                  # full dataset (300 vendors, 2,000 invoices)
    python -m apflow generate | validate | run | evaluate | reproduce | explain | docs
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from apflow.config import ROOT, load_policy
from apflow.evaluation import evaluate
from apflow.export import export_dataset, read_csv, write_json
from apflow.generator import generate
from apflow.pipeline.run import run_pipeline
from apflow.report import build_report
from apflow.export import mariadb_schema
from apflow.schema import data_dictionary_markdown
from apflow.validation import validate


def _paths(args):
    name = args.name or ("full" if args.scale == 1.0 else f"scale_{args.scale}")
    return ROOT / "data" / name, ROOT / "output" / name, name


def cmd_generate(args):
    policy = load_policy(args.policy, scale=args.scale, seed=args.seed)
    data_dir, _, name = _paths(args)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    command = f"python -m apflow generate --scale {args.scale} --seed {policy.seed} --name {name}"
    manifest = export_dataset(generate(policy), data_dir, policy, command)
    print(f"[generate] {data_dir}  seed={policy.seed}")
    for t, n in manifest["row_counts"].items():
        print(f"   {t:<24}{n:>7,}")
    return 0


def cmd_validate(args):
    policy = load_policy(args.policy, scale=args.scale, seed=args.seed)
    data_dir, _, _ = _paths(args)
    summary = validate(data_dir, policy)
    failed = [c for c in summary["checks"] if c["status"] == "FAIL"]
    print(f"[validate] {summary['checks_total'] - len(failed)}/{summary['checks_total']} checks passed")
    for c in failed:
        print(f"   FAIL {c['category']}: {c['check']} ({c['failures']}) e.g. {c['examples'][:2]}")
    return 0 if not failed else 1


def cmd_run(args):
    policy = load_policy(args.policy, scale=args.scale, seed=args.seed)
    data_dir, out_dir, _ = _paths(args)
    result = run_pipeline(data_dir, out_dir, policy)
    states = {}
    for d in result["decisions"]:
        states[d.final_state] = states.get(d.final_state, 0) + 1
    print(f"[run] {len(result['decisions'])} invoices -> {out_dir}")
    for s, n in sorted(states.items()):
        print(f"   {s:<20}{n:>6}")
    return 0


def cmd_evaluate(args):
    data_dir, out_dir, name = _paths(args)
    m = evaluate(data_dir, out_dir)
    validation = json.loads((data_dir / "validation_summary.json").read_text()) \
        if (data_dir / "validation_summary.json").exists() else {"checks": [], "checks_total": 0, "checks_failed": 0}
    manifest = json.loads((data_dir / "manifest.json").read_text())
    report = build_report(m, validation, out_dir, name, manifest)
    a, k = m["acceptance"], m["kpis"]
    print("[evaluate] acceptance: " + ", ".join(f"{x}={v:.1%}" for x, v in a.items()))
    print(f"   safety gate (blocked marked payment-ready = 0): {m['safety']['gate']}")
    print(f"   straight-through {k['straight_through_rate']:.1%} | duplicates prevented ${float(k['duplicate_payments_prevented_value']):,.2f}"
          f" | over-billing stopped ${float(k['overbilling_prevented_value']):,.2f}")
    print(f"   report: {report}")
    ok = m["safety"]["gate"] == "PASS"
    return 0 if ok else 1


def cmd_reproduce(args):
    """Generate twice with the same seed and compare row counts + checksums (Step 10)."""
    policy = load_policy(args.policy, scale=args.scale, seed=args.seed)
    with tempfile.TemporaryDirectory() as tmp:
        runs = []
        for i in (1, 2):
            out = Path(tmp) / f"run{i}"
            runs.append(export_dataset(generate(load_policy(args.policy, scale=args.scale, seed=policy.seed)),
                                       out, policy, "reproduce"))
    a, b = runs
    diffs = [f for f in a["files"] if a["files"][f] != b["files"].get(f)]
    result = {"seed": policy.seed, "scale": args.scale, "identical": not diffs and a["row_counts"] == b["row_counts"],
              "files_compared": len(a["files"]), "differing_files": diffs, "row_counts": a["row_counts"],
              "checksums_run1": a["files"], "checksums_run2": b["files"]}
    _, out_dir, _ = _paths(args)
    write_json(out_dir / "reproducibility_report.json", result)
    print(f"[reproduce] {len(a['files'])} files compared, identical={result['identical']}")
    return 0 if result["identical"] else 1


def cmd_explain(args):
    _, out_dir, _ = _paths(args)
    dec = {d["invoice_id"]: d for d in read_csv(out_dir / "decisions.csv")}
    d = dec.get(args.invoice_id)
    if not d:
        print(f"invoice {args.invoice_id} not found")
        return 1
    print(f"{d['invoice_id']}  vendor={d['vendor_id']}  po={d['po_id'] or '-'}  total={d['stated_total']}")
    print(f"  state={d['final_state']}  match={d['match_status']}  queue={d['route_queue'] or '-'}  "
          f"payment_ready={d['payment_ready']}")
    print(f"  why: {d['explanation']}")
    print("  audit trail:")
    for e in read_csv(out_dir / "invoice_events.csv"):
        if e["invoice_id"] == args.invoice_id:
            print(f"    {e['event_time']}  {e['from_state'] or '(start)':>17} -> {e['to_state']:<18} {e['actor']:<18} {e['reason']}")
    return 0


def cmd_docs(args):
    path = ROOT / "docs" / "data_dictionary.md"
    path.write_text(data_dictionary_markdown() + "\n", encoding="utf-8", newline="\n")
    schema = ROOT / "database" / "schema_mariadb.sql"
    schema.write_text(mariadb_schema() + "\n", encoding="utf-8", newline="\n")
    print(f"[docs] wrote {path} and {schema}")
    return 0


def _publish(out_dir, name, files):
    """Copy key reports of the full dataset to docs/results so they are visible on GitHub."""
    if name != "full":
        return
    target = ROOT / "docs" / "results"
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copyfile(out_dir / f, target / f)


def cmd_whatif(args):
    from apflow import whatif
    policy = load_policy(args.policy, scale=args.scale, seed=args.seed)
    data_dir, out_dir, name = _paths(args)
    r = whatif.run_whatif(data_dir, policy)
    whatif.save(r, out_dir)
    _publish(out_dir, name, ["whatif.md"])
    print("[whatif] price tolerance -> touchless / good invoices blocked / overcharge paid")
    for x in r["rows"]:
        print(f"   {x['tolerance_pct']:>4.0f}%{'*' if x['current_policy'] else ' '} {x['touchless_rate']:>6.1%}  "
              f"{x['good_invoices_blocked']:>4}  ${float(x['overcharge_paid_usd']):>10,.2f}")
    return 0


def cmd_robustness(args):
    from apflow import robustness
    policy = load_policy(args.policy, scale=args.scale, seed=args.seed)
    data_dir, out_dir, name = _paths(args)
    r = robustness.run_robustness(data_dir, policy)
    robustness.save(r, out_dir)
    _publish(out_dir, name, ["robustness.md"])
    print(f"[robustness] {r['documents_damaged']} damaged documents, {r['unsafe_payments']} unsafe payments")
    return 0 if r["unsafe_payments"] == 0 else 1


def cmd_impact(args):
    from apflow import impact
    _, out_dir, name = _paths(args)
    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    r = impact.compute_impact(metrics)
    impact.save(r, out_dir, name)
    _publish(out_dir, name, ["impact.md"])
    print(f"[impact] {r['hours_saved']:,.0f} hours saved (assumption-based), {r['fte_freed']} FTE")
    return 0


def cmd_all(args):
    for step in (cmd_generate, cmd_validate, cmd_run, cmd_evaluate, cmd_whatif, cmd_robustness, cmd_impact,
                 cmd_reproduce):
        code = step(args)
        if code:
            return code
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="apflow", description="AP invoice automation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("generate", cmd_generate), ("validate", cmd_validate), ("run", cmd_run),
                     ("evaluate", cmd_evaluate), ("reproduce", cmd_reproduce), ("all", cmd_all),
                     ("explain", cmd_explain), ("docs", cmd_docs), ("whatif", cmd_whatif),
                     ("robustness", cmd_robustness), ("impact", cmd_impact)]:
        p = sub.add_parser(name)
        p.add_argument("--scale", type=float, default=1.0, help="1.0 = full volume, 0.1 = starter")
        p.add_argument("--seed", type=int, default=None, help="override seed in config/policy.json")
        p.add_argument("--name", default=None, help="dataset name (folder under data/ and output/)")
        p.add_argument("--policy", default=None, help="path to policy JSON")
        if name == "explain":
            p.add_argument("invoice_id")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
