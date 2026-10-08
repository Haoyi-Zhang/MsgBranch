"""Descriptive paired statistics for the two frozen generated studies.

Intervals and p-values describe these constructed families only; they are not
population estimates of field-defect recall.
"""
from __future__ import annotations
from pathlib import Path
import csv
import json
import math

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
Z = 1.959963984540054

METHODS = {
    "ordinary7": "ordinary7_detects",
    "branch_only": "branch_only_detects",
    "source_only": "source_only_detects",
    "product": "product_detects",
    "equal_budget_even": "equal_budget_even_detects",
}


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return [centre - half, centre + half]


def exact_mcnemar(a: list[bool], b: list[bool]) -> dict:
    if len(a) != len(b):
        raise ValueError("paired vectors differ")
    a_only = sum(x and not y for x, y in zip(a, b))
    b_only = sum(y and not x for x, y in zip(a, b))
    n = a_only + b_only
    if n == 0:
        p = 1.0
    else:
        tail = sum(math.comb(n, i) for i in range(min(a_only, b_only) + 1)) / (2**n)
        p = min(1.0, 2 * tail)
    return {"a_only": a_only, "b_only": b_only, "discordant": n, "two_sided_exact_p": p}


def analyze(name: str) -> dict:
    families = json.loads((RESULTS / f"{name}.json").read_text())
    active = [row for row in families if row["active_mutation"]]
    out = {"active_mutations": len(active), "methods": {}, "paired_against_product": {}}
    for method, field in METHODS.items():
        vector = [bool(row[field]) for row in active]
        hits = sum(vector)
        out["methods"][method] = {
            "hits": hits,
            "misses": len(active) - hits,
            "proportion": hits / len(active),
            "wilson_95": wilson(hits, len(active)),
        }
    product = [bool(row[METHODS["product"]]) for row in active]
    for method in ("ordinary7", "branch_only", "source_only", "equal_budget_even"):
        comparator = [bool(row[METHODS[method]]) for row in active]
        out["paired_against_product"][method] = exact_mcnemar(product, comparator)
    random_trials = [trial["detects"] for row in active for trial in row["random_trials"]]
    out["equal_budget_random"] = {
        "trials": len(random_trials),
        "hits": sum(random_trials),
        "proportion": sum(random_trials) / len(random_trials),
        "unit": "family-seed trial",
    }
    return out

report = {
    "validation": analyze("validation"),
    "confirmation": analyze("confirmation"),
    "interpretation": (
        "Exact paired tests and Wilson intervals describe the frozen constructed active-mutation families. "
        "They do not estimate prevalence, real-project recall, or independent field performance."
    ),
}
(RESULTS / "statistical-analysis.json").write_text(json.dumps(report, indent=2) + "\n")
with (RESULTS / "statistical-analysis.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["study", "method", "hits", "active", "proportion", "wilson_low", "wilson_high"])
    for study in ("validation", "confirmation"):
        active = report[study]["active_mutations"]
        for method, row in report[study]["methods"].items():
            writer.writerow([study, method, row["hits"], active, row["proportion"], *row["wilson_95"]])
print(json.dumps(report, indent=2))
