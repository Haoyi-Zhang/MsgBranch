"""Evaluate project qualification on frozen controls and public field slices."""
from __future__ import annotations

from pathlib import Path
import argparse
import json

if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.project import audit_project

ROOT = Path(__file__).resolve().parents[1]


def _status_changes(direct: dict, flow: dict) -> dict[str, int]:
    if len(direct["findings"]) != len(flow["findings"]):
        raise ValueError("direct/flow finding cardinality differs")
    changes = {
        "unknown_to_clean": 0,
        "unknown_to_error": 0,
        "clean_to_unknown": 0,
        "error_to_unknown": 0,
        "other_changes": 0,
    }
    for before, after in zip(direct["findings"], flow["findings"], strict=True):
        identity_before = (before.get("call", {}), before.get("catalog"))
        identity_after = (after.get("call", {}), after.get("catalog"))
        if identity_before != identity_after:
            raise ValueError("direct/flow finding identities differ")
        left, right = before["status"], after["status"]
        if left == right:
            continue
        key = f"{left}_to_{right}"
        if key in changes:
            changes[key] += 1
        else:
            changes["other_changes"] += 1
    return changes


def one(source: Path, catalogs: list[Path], **kwargs) -> dict:
    flow = audit_project(source, catalogs, analysis_mode="flow", **kwargs)
    direct = audit_project(source, catalogs, analysis_mode="direct", **kwargs)
    return {
        "source": str(source.relative_to(ROOT)),
        "catalogs": [str(path.relative_to(ROOT)) for path in catalogs],
        "summary": flow["summary"],
        "direct_summary": direct["summary"],
        "ablation": _status_changes(direct, flow),
        "findings": flow["findings"],
        "direct_findings": direct["findings"],
    }


def evaluate() -> dict:
    controls = []
    for folder in sorted((ROOT / "data/controls").iterdir()):
        source, catalog = folder / "call.py", folder / "messages.po"
        if source.exists() and catalog.exists():
            controls.append({"case": folder.name, **one(source, [catalog], max_count=200)})

    field = [
        {
            "case": "sphinx-before-ja-strict",
            **one(
                ROOT / "data/upstream/sphinx/before.py",
                [ROOT / "data/upstream/sphinx/ja.po"],
                max_count=2,
                require_catalog=True,
                overloaded_callees=("__",),
            ),
            "scope": "source-extracted function; wrapper binding supplied explicitly",
        },
        {
            "case": "sphinx-after-ja-strict",
            **one(
                ROOT / "data/upstream/sphinx/after.py",
                [ROOT / "data/upstream/sphinx/ja.po"],
                max_count=2,
                require_catalog=True,
                overloaded_callees=("__",),
            ),
            "scope": "source-extracted function; path feasibility is not inferred",
        },
        {
            "case": "jupyter-2.17-source",
            **one(
                ROOT / "data/upstream/jupyter/running_server_info.py",
                [ROOT / "data/upstream/jupyter/notebook.po"],
                max_count=200,
            ),
            "scope": "exact source slice; indirect percent formatting is recovered intraprocedurally",
        },
    ]
    for version in ("before", "after"):
        field.append(
            {
                "case": f"openhangar-{version}-service-supplier",
                **one(
                    ROOT / f"data/openhangar/{version}/project_calls.py",
                    [
                        ROOT / f"data/openhangar/{version}/fr.po",
                        ROOT / f"data/openhangar/{version}/nl.po",
                    ],
                    max_count=30,
                    plural_callees=("ngettext", "_ln"),
                ),
                "scope": (
                    "exact service and template calls normalized into a parseable Python slice; "
                    "Jinja execution is separately replayed"
                ),
            }
        )
    field.append(
        {
            "case": "azm-po-present",
            **one(
                ROOT / "data/azm-build/source.py",
                [ROOT / "data/azm-build/messages.po"],
                max_count=1,
                require_catalog=True,
            ),
            "scope": "shows PO/call compatibility only; absent MO is separately replayed",
        }
    )

    all_rows = controls + field
    ablation_keys = tuple(all_rows[0]["ablation"]) if all_rows else ()
    summary = {
        "evaluation_mode": "current-source",
        "control_cases": len(controls),
        "field_slices": len(field),
        "call_catalog_findings": sum(row["summary"]["findings"] for row in all_rows),
        "clean": sum(row["summary"]["clean"] for row in all_rows),
        "errors": sum(row["summary"]["errors"] for row in all_rows),
        "unknown": sum(row["summary"]["unknown"] for row in all_rows),
        "selected_patterns": sum(row["summary"]["selected_patterns"] for row in all_rows),
        "direct_clean": sum(row["direct_summary"]["clean"] for row in all_rows),
        "direct_errors": sum(row["direct_summary"]["errors"] for row in all_rows),
        "direct_unknown": sum(row["direct_summary"]["unknown"] for row in all_rows),
        "direct_selected_patterns": sum(
            row["direct_summary"]["selected_patterns"] for row in all_rows
        ),
        "flow_recovered_calls": sum(row["summary"]["flow_recovered_calls"] for row in all_rows),
        "type_error_witnesses": sum(row["summary"]["type_error_witnesses"] for row in all_rows),
        "type_unknown_witnesses": sum(row["summary"]["type_unknown_witnesses"] for row in all_rows),
        "ablation": {
            key: sum(row["ablation"][key] for row in all_rows) for key in ablation_keys
        },
        "interpretation": (
            "Errors are qualified call/catalog or explicit catalog-presence obligations; unknowns are retained for "
            "dynamic IDs, unresolved suppliers, unsupported syntax, or feasibility uncertainty. The direct/flow "
            "ablation measures classification changes on the same findings, including conservative tightening to unknown. "
            "A change to unknown is not an established runtime failure. Counts are findings, not independent defects."
        ),
    }
    return {"summary": summary, "controls": controls, "field_slices": field}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "results/project-audit.json")
    args = parser.parse_args()
    result = evaluate()
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
