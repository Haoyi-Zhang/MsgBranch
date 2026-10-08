from scripts.holdout_evaluate import evaluate


def test_postfreeze_independent_project_holdout_is_clean_and_executable():
    result = evaluate()
    summary = result["summary"]
    assert summary["status"] == "pass"
    assert summary["projects"] == 2
    assert summary["runtime_executions"] == 10
    assert summary["runtime_errors"] == 0
    assert summary["errors"] == 0
    assert summary["unknown"] == 0
    assert summary["analyzer_hashes_match_freeze"]
