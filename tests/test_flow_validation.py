from scripts.flow_validation import evaluate


def test_flow_validation_matches_direct_runtime_on_all_constructed_controls():
    result = evaluate()
    summary = result["summary"]
    assert summary["status"] == "pass"
    assert summary["flow_exact"] == summary["controls"]
    assert summary["flow_false_positive_controls"] == 0
    assert summary["flow_false_negative_controls"] == 0
    assert summary["direct_exact"] < summary["flow_exact"]
