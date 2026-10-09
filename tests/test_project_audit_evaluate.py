import copy
from types import SimpleNamespace

import pytest

from msgbranch.runtime import CatalogRuntime
from scripts.audit_results import audit_project_qualification
from scripts.project_audit_evaluate import ROOT, evaluate


def test_project_audit_evaluation_retains_errors_and_unknowns():
    result = evaluate()
    summary = result["summary"]
    assert summary["control_cases"] >= 20
    assert summary["field_slices"] == 6
    assert summary["errors"] > 0
    assert summary["unknown"] > 0
    assert summary["selected_patterns"] > summary["field_slices"]
    assert summary["direct_unknown"] > summary["unknown"]
    assert summary["ablation"]["unknown_to_clean"] > 0
    assert summary["ablation"]["unknown_to_error"] > 0
    assert audit_project_qualification(result)["transitions"] == summary["ablation"]
    tightened = []
    for row in result["controls"] + result["field_slices"]:
        for direct, flow in zip(row["direct_findings"], row["findings"], strict=True):
            if direct["status"] in {"clean", "error"} and flow["status"] == "unknown":
                assert flow["witnesses"]
                assert all(w["qualification"]["reason"] == "unresolved use reachability" for w in flow["witnesses"])
                assert all(w["flow"]["reachable"] is None for w in flow["witnesses"])
                tightened.append((row["case"], flow["call"]["singular"], direct["status"]))
    assert {(case, message) for case, message, before in tightened if before == "clean"} == {
        (f"sphinx-{version}-ja-strict", message)
        for version in ("before", "after") for message in ("succeeded", "finished with problems")
    }
    assert sum(before == "clean" for _, _, before in tightened) == summary["ablation"]["clean_to_unknown"]
    assert sum(before == "error" for _, _, before in tightened) == summary["ablation"]["error_to_unknown"]
    by_case = {row["case"]: row for row in result["field_slices"]}
    assert by_case["azm-po-present"]["summary"]["errors"] == 0
    before = by_case["sphinx-before-ja-strict"]
    assert before["direct_summary"]["errors"] == 0
    unresolved_selectors = [f for f in before["direct_findings"] if f["call"]["kind"] == "plural"]
    assert unresolved_selectors
    assert all(f["status"] == "unknown" and f["call"]["count_binding"] == "unknown"
               for f in unresolved_selectors)
    assert all(f["reason"] == "plural selector is outside the admitted count binding"
               for f in unresolved_selectors)
    assert by_case["sphinx-before-ja-strict"]["summary"]["unknown"] > 0


def test_sphinx_status_tightenings_are_unmodeled_guards_not_native_errors():
    catalog = ROOT / "data/upstream/sphinx/ja.po"
    for version in ("before", "after"):
        source = ROOT / f"data/upstream/sphinx/{version}.py"
        namespace = {}
        # Reviewed retained local functions only: no application import/setup.
        exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), namespace)
        runtime = CatalogRuntime(catalog)
        for statuscode in (0, 1):
            expected = runtime.gettext("succeeded" if statuscode == 0 else "finished with problems")
            for warncount in (0, 1, 2):
                for warningiserror in (False, True):
                    state = SimpleNamespace(statuscode=statuscode, _warncount=warncount, warningiserror=warningiserror)
                    runtime.reset()
                    output = namespace["build_message"](state, runtime.sphinx)
                    assert expected in output
                    assert runtime.trace[0].singular == ("succeeded" if statuscode == 0 else "finished with problems")
        # The historical count-one lookup-kind repair remains distinct from
        # the current static reachability unknowns.
        runtime.reset()
        namespace["build_message"](SimpleNamespace(statuscode=0, _warncount=1, warningiserror=False), runtime.sphinx)
        assert runtime.trace[-1].resolution == ("source-fallback" if version == "before" else "catalog")


def test_project_accounting_rejects_erased_tightening_and_changed_identity():
    result = evaluate()
    changed = copy.deepcopy(result)
    changed["summary"]["ablation"]["clean_to_unknown"] = 0
    with pytest.raises(ValueError, match="total transition"):
        audit_project_qualification(changed)
    changed = copy.deepcopy(result)
    changed["controls"][0]["direct_findings"][0]["call"]["line"] += 1
    with pytest.raises(ValueError, match="identity"):
        audit_project_qualification(changed)
