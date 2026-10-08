"""Evaluate two retained external-project localization regression boundaries.

The retained files are trusted, license-preserving adapted slices.  Executing
those slices provides a runtime oracle for their local call boundary; it does
not execute either full application or establish linguistic correctness.
"""
from __future__ import annotations

from pathlib import Path
import argparse
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

# Reviewed current classification contract. The singular Solaar lookup has no
# plural-count binding, so its n == 0 reachability remains explicitly unknown.
BOUNDARIES = {
    "solaar": (
        ("singular", "No paired devices.", "unknown"),
        ("plural", "%(count)s paired device.", "clean"),
    ),
    "virt-manager": (
        ("plural", "Waiting %(minutes)d minute for the installation to complete.", "clean"),
    ),
}


def _expected_output(case: str, runtime: CatalogRuntime, count: int) -> str:
    """Reviewed local boundary oracle, not a second translation engine."""
    if case == "solaar":
        if count == 0:
            return runtime.gettext("No paired devices.")
        return runtime.ngettext("%(count)s paired device.", "%(count)s paired devices.", count) % {"count": count}
    return runtime.ngettext(
        "Waiting %(minutes)d minute for the installation to complete.",
        "Waiting %(minutes)d minutes for the installation to complete.", count,
    ) % {"minutes": count}


def _boundary_contract(case: str, findings: list[dict]) -> bool:
    actual = [(f["call"]["kind"], f["call"]["singular"], f["status"]) for f in findings]
    if sorted(actual) != sorted(BOUNDARIES[case]):
        return False
    for finding in findings:
        if finding["status"] == "unknown":
            witnesses = finding.get("witnesses", [])
            if not witnesses or not all(
                w["qualification"].get("reason") == "unresolved use reachability"
                and (w.get("flow") or {}).get("reachable") is None
                for w in witnesses
            ):
                return False
    return True


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _execute(source: Path, catalog: Path, case: str) -> list[dict]:
    runtime = CatalogRuntime(catalog)
    oracle = CatalogRuntime(catalog)
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
            expected = _expected_output(case, oracle, count)
            rows.append(
                {
                    "count": count,
                    "status": "ok",
                    "output": output,
                    "expected_output": expected,
                    "matches_expected": output == expected,
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


def evaluate(*, mode: str = "current-regression") -> dict:
    if mode not in {"current-regression", "frozen-source"}:
        raise ValueError("mode must be current-regression or frozen-source")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    actual_hashes = {
        path: _sha(ROOT / path) for path in protocol["analyzer_sha256"]
    }
    frozen = actual_hashes == protocol["analyzer_sha256"]
    records = []
    for case, source, catalog in CASES:
        flow = audit_project(source, [catalog], max_count=max(COUNTS), analysis_mode="flow")
        direct = audit_project(source, [catalog], max_count=max(COUNTS), analysis_mode="direct")
        runtime_rows = _execute(source, catalog, case)
        provenance = json.loads((source.parent / "PROVENANCE.json").read_text(encoding="utf-8"))
        records.append(
            {
                "case": case,
                "source": source.relative_to(ROOT).as_posix(),
                "catalog": catalog.relative_to(ROOT).as_posix(),
                "source_identity": {
                    "repository": provenance["repository"],
                    "commit": provenance["commit"],
                    "source_sha256": _sha(source),
                    "catalog_sha256": _sha(catalog),
                    "provenance_sha256": _sha(source.parent / "PROVENANCE.json"),
                },
                "flow_summary": flow["summary"],
                "direct_summary": direct["summary"],
                "findings": flow["findings"],
                "direct_findings": direct["findings"],
                "boundary_contract_matches": _boundary_contract(case, flow["findings"]),
                "runtime": runtime_rows,
            }
        )
    checks = {
        "declared_counts_match": list(COUNTS) == protocol["selection"]["counts"],
        "current_boundary_contract": all(row["boundary_contract_matches"] for row in records),
        "native_boundary_oracle": all(item.get("matches_expected", False) for row in records for item in row["runtime"]),
    }
    if mode == "frozen-source":
        checks["analyzer_freeze"] = frozen
        checks["all_findings_qualified"] = all(
            row["flow_summary"]["errors"] == row["flow_summary"]["unknown"] == 0 for row in records
        )
        # The historical frozen analyzer's all-clean contract differs from the
        # explicitly reviewed current residual-unknown contract.
        checks.pop("current_boundary_contract")
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
            "evaluation_mode": mode,
            "qualification_status": "error" if any(row["flow_summary"]["errors"] for row in records)
            else ("unknown" if any(row["flow_summary"]["unknown"] for row in records) else "clean"),
            "status": "pass" if all(checks.values()) else "fail",
            "status_semantics": "Regression contract and native boundary-oracle checks; pass does not mean all findings are clean.",
            "scope": (
                "Two retained external-project adapted boundaries, not a blind holdout of this implementation; validates local applicability "
                "with explicit residual unknowns, not whole-project recall or linguistic quality."
            ),
        },
        "freeze": {
            "frozen_on": protocol["frozen_on"],
            "expected": protocol["analyzer_sha256"],
            "actual": actual_hashes,
        },
        "selection": protocol["selection"],
        "interpretation": protocol["interpretation"],
        "checks": checks,
        "records": records,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("current-regression", "frozen-source"), default="current-regression")
    parser.add_argument("--out", type=Path, default=ROOT / "results/holdout.json")
    args = parser.parse_args()
    result = evaluate(mode=args.mode)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if result["summary"]["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
