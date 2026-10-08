"""Run the LocalHero offline-check placeholder component on retained PO inputs."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import json
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.localhero_core import flatten_catalog, run_component
from msgbranch.runtime import CatalogRuntime

ROOT = Path(__file__).resolve().parents[1]
rows = []
node_cases = []

for population, manifest_path in [
    ("controls", "data/control-manifest.json"),
    ("validation", "data/validation/manifest.json"),
    ("confirmation", "data/confirmation/manifest.json"),
]:
    manifest = json.loads((ROOT / manifest_path).read_text())
    if isinstance(manifest, dict):
        manifest = manifest.get("cases", manifest.get("families", manifest))
    for case in manifest:
        runtime = CatalogRuntime(ROOT / case["catalog"])
        source, target = flatten_catalog(runtime.catalog)
        node_cases.append({
            "meta": {
                "population": population,
                "case": case["id"],
                "category": case.get("category", case.get("kind")),
                "catalog": case["catalog"],
            },
            "source": source,
            "target": target,
        })

for version in ("before", "after"):
    for locale in ("fr", "nl"):
        path = f"data/openhangar/{version}/{locale}.po"
        runtime = CatalogRuntime(ROOT / path)
        source, target = flatten_catalog(runtime.catalog)
        node_cases.append({
            "meta": {
                "population": "openhangar",
                "case": f"{version}-{locale}",
                "category": version,
                "catalog": path,
            },
            "source": source,
            "target": target,
        })

rows = run_component(node_cases)
(ROOT / "results" / "localhero-core.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")

summary = {}
for population in ("controls", "validation", "confirmation", "openhangar"):
    selected = [row for row in rows if row["population"] == population]
    by_category = {}
    for category in sorted({row["category"] for row in selected}, key=str):
        group = [row for row in selected if row["category"] == category]
        by_category[category] = {
            "units": len(group),
            "errors": sum(row["error"] for row in group),
            "hints": sum(row["hint"] for row in group),
        }
    summary[population] = {
        "units": len(selected),
        "errors": sum(row["error"] for row in selected),
        "hints": sum(row["hint"] for row in selected),
        "by_category": by_category,
    }
summary["scope"] = (
    "LocalHero CLI commit af81321 placeholder-mismatch source component on already-flattened PO maps; "
    "hints and errors are separated; not the complete CLI or its other checks."
)
(ROOT / "results" / "localhero-core-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
