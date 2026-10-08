from scripts.project_audit_evaluate import evaluate


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
    assert summary["ablation"]["clean_to_unknown"] == 0
    assert summary["ablation"]["error_to_unknown"] == 0
    by_case = {row["case"]: row for row in result["field_slices"]}
    assert by_case["azm-po-present"]["summary"]["errors"] == 0
    assert by_case["sphinx-before-ja-strict"]["summary"]["errors"] > 0
