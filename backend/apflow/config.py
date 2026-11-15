"""Loads the business policy (config/policy.json) and scales volumes.

Keeping every threshold in one JSON file means the process owner can change a
tolerance or an approval limit without touching code, and every run records
which policy it used.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent     # .../backend
ROOT = BACKEND_ROOT.parent                                # repository root (data/, output/, docs/)
DEFAULT_POLICY_PATH = BACKEND_ROOT / "config" / "policy.json"


def allocate(total: int, weights: dict) -> dict:
    """Split an integer total by weights using the largest-remainder method.

    Deterministic: ties are broken by the key order in `weights`.
    allocate(2000, {"a": .7, "b": .3}) -> {"a": 1400, "b": 600}
    """
    weight_sum = sum(weights.values())
    raw = {k: total * w / weight_sum for k, w in weights.items()}
    result = {k: math.floor(v) for k, v in raw.items()}
    remainder = total - sum(result.values())
    order = sorted(weights, key=lambda k: (-(raw[k] - result[k]), list(weights).index(k)))
    for k in order[:remainder]:
        result[k] += 1
    return result


@dataclass
class Policy:
    raw: dict
    seed: int
    fiscal_year: int
    as_of: date
    po_start: date
    po_end: date
    currency: str
    volumes: dict
    scenario_mix: dict
    sub_scenario_mix: dict
    price_tolerance_pct: Decimal
    amount_tolerance: Decimal
    tax_rates: dict
    approval_matrix: list
    non_po_minimum_tier: int
    source_path: str = ""
    scale: float = 1.0
    extra: dict = field(default_factory=dict)

    # ---- approval policy (shared by ground-truth labelling and the pipeline) ----
    def approval_tier(self, total: Decimal, non_po: bool = False) -> dict:
        tier = None
        for row in self.approval_matrix:
            limit = row["max_total"]
            if limit is None or total <= Decimal(limit):
                tier = row
                break
        if non_po and tier["tier"] < self.non_po_minimum_tier:
            tier = next(r for r in self.approval_matrix if r["tier"] == self.non_po_minimum_tier)
        return tier

    def approval_roles(self, total: Decimal, non_po: bool = False) -> list:
        return list(self.approval_tier(total, non_po)["roles"])


def load_policy(path=None, scale: float = 1.0, seed: int | None = None) -> Policy:
    path = Path(path) if path else DEFAULT_POLICY_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    if seed is not None:
        raw["seed"] = seed
    volumes = {k: max(1, round(v * scale)) for k, v in raw["volumes"].items()}
    # PO lines can never be fewer than POs (every PO has >= 1 line)
    volumes["purchase_order_lines"] = max(volumes["purchase_order_lines"], volumes["purchase_orders"])
    volumes["vendors"] = max(volumes["vendors"], 10)
    return Policy(
        raw=raw,
        seed=int(raw["seed"]),
        fiscal_year=int(raw["fiscal_year"]),
        as_of=date.fromisoformat(raw["as_of_date"]),
        po_start=date.fromisoformat(raw["po_date_window"]["start"]),
        po_end=date.fromisoformat(raw["po_date_window"]["end"]),
        currency=raw["currency"],
        volumes=volumes,
        scenario_mix=raw["scenario_mix"],
        sub_scenario_mix=raw["sub_scenario_mix"],
        price_tolerance_pct=Decimal(raw["tolerances"]["price_pct"]),
        amount_tolerance=Decimal(raw["tolerances"]["amount_abs"]),
        tax_rates={k: Decimal(v) for k, v in raw["tax_codes"].items()},
        approval_matrix=raw["approval_matrix"],
        non_po_minimum_tier=int(raw["non_po_minimum_tier"]),
        source_path=str(path),
        scale=scale,
    )
