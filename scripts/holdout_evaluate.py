"""Evaluate two retained external-project localization regression boundaries.

The retained files are trusted, license-preserving adapted slices.  Executing
those slices provides a runtime oracle for their local call boundary; it does
not execute either full application or establish linguistic correctness.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json

if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.project import audit_project
from msgbranch.runtime import CatalogRuntime

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "data" / "holdout" / "PROTOCOL.json"
COUNTS = (0, 1, 2, 5, 100)
CASES = (
    ("solaar", ROOT / "data/holdout/solaar/call.py", ROOT / "data/holdout/solaar/messages.po"),
    (
        "virt-manager",
        ROOT / "data/holdout/virt-manager/call.py",
        ROOT / "data/holdout/virt-manager/messages.po",
    ),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _execute(source: Path, catalog: Path) -> list[dict]:
    runtime = CatalogRuntime(catalog)
    namespace = {
        "gettext": runtime.gettext,
        "ngettext": runtime.ngettext,
        "pgettext": runtime.pgettext,
        "npgettext": runtime.npgettext,
    }
    exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), namespace)
    rows = []
    for count in COUNTS:
        runtime.reset()
        try:
            output = namespace["message"](count)
            rows.append(
                {
                    "count": count,
                    "status": "ok",
                    "output": output,
                    "lookups": runtime.serialize_trace(),
                }
            )
        except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
            rows.append(
                {
                    "count": count,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "lookups": runtime.serialize_trace(),
                }
            )
    return rows


def evaluate() -> dict:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    actual_hashes = {
        path: _sha(ROOT / path) for path in protocol["analyzer_sha256"]
    }
    frozen = actual_hashes == protocol["analyzer_sha256"]
    records = []
    for case, source, catalog in CASES:
        flow = audit_project(source, [catalog], max_count=max(COUNTS), analysis_mode="flow")
        direct = audit_project(source, [catalog], max_count=max(COUNTS), analysis_mode="direct")
        runtime_rows = _execute(source, catalog)
        records.append(
            {
                "case": case,
                "source": str(source.relative_to(ROOT)),
                "catalog": str(catalog.relative_to(ROOT)),
                "flow_summary": flow["summary"],
                "direct_summary": direct["summary"],
                "runtime": runtime_rows,
            }
        )
    result = {
        "summary": {
            "projects": len(records),
            "call_catalog_findings": sum(row["flow_summary"]["findings"] for row in records),
            "clean": sum(row["flow_summary"]["clean"] for row in records),
            "errors": sum(row["flow_summary"]["errors"] for row in records),
            "unknown": sum(row["flow_summary"]["unknown"] for row in records),
            "runtime_executions": sum(len(row["runtime"]) for row in records),
            "runtime_errors": sum(
                item["status"] == "error" for row in records for item in row["runtime"]
            ),
            "analyzer_hashes_match_freeze": frozen,
            "status": "pass"
            if frozen
            and all(row["flow_summary"]["errors"] == 0 for row in records)
            and all(row["flow_summary"]["unknown"] == 0 for row in records)
            and all(item["status"] == "ok" for row in records for item in row["runtime"])
            else "fail",
            "scope": (
                "Two retained external-project adapted boundaries, not a blind holdout of this implementation; validates local applicability "
                "and absence of alarms on these calls, not whole-project recall or linguistic quality."
            ),
        },
        "freeze": {
            "expected": protocol["analyzer_sha256"],
            "actual": actual_hashes,
        },
        "records": records,
    }
    return result


def main() -> None:
    result = evaluate()
    (ROOT / "results/holdout.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if result["summary"]["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
