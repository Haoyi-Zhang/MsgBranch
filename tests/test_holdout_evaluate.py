import copy

import pytest

from scripts import holdout_evaluate
from scripts.audit_results import audit_holdout
from scripts.holdout_evaluate import evaluate


def test_current_known_regressions_keep_freeze_and_residual_unknown():
    result = evaluate()
    summary = result["summary"]
    assert summary["status"] == "pass", result
    assert summary["projects"] == 2
    assert summary["runtime_executions"] == 10
    assert summary["runtime_errors"] == 0
    assert summary["errors"] == 0
    assert summary["clean"] == 2
    assert summary["unknown"] == 1
    assert summary["qualification_status"] == "unknown"
    assert summary["evaluation_mode"] == "current-regression"
    assert not summary["analyzer_hashes_match_freeze"]
    assert result["freeze"]["expected"] != result["freeze"]["actual"]
    assert "not a blind holdout" in result["selection"]["rule"]
    assert all(result["checks"].values())
    assert audit_holdout(result)["findings"] == 3
    solaar = next(row for row in result["records"] if row["case"] == "solaar")
    unknown = [f for f in solaar["findings"] if f["status"] == "unknown"]
    assert len(unknown) == 1 and unknown[0]["call"]["singular"] == "No paired devices."
    assert all(w["flow"]["reachable"] is None for w in unknown[0]["witnesses"])
    assert all(w["qualification"]["reason"] == "unresolved use reachability" for w in unknown[0]["witnesses"])
    assert all(row["source_identity"]["commit"] for row in result["records"])


def test_strict_frozen_source_mode_still_rejects_changed_analyzer():
    result = evaluate(mode="frozen-source")
    assert result["summary"]["status"] == "fail"
    assert result["checks"]["analyzer_freeze"] is False
    assert result["checks"]["all_findings_qualified"] is False
    with pytest.raises(ValueError, match="validation failed"):
        audit_holdout(result)


def test_current_regression_rejects_native_oracle_disagreement(monkeypatch):
    execute = holdout_evaluate._execute
    def wrong_output(*args):
        rows = execute(*args)
        rows[0]["output"] = "owned wrong output"
        rows[0]["matches_expected"] = False
        return rows
    monkeypatch.setattr(holdout_evaluate, "_execute", wrong_output)
    result = evaluate()
    assert result["summary"]["status"] == "fail"
    assert result["checks"]["native_boundary_oracle"] is False


def test_holdout_accounting_rejects_fabricated_clean_count_and_match():
    result = evaluate()
    changed = copy.deepcopy(result)
    changed["summary"]["unknown"] = 0
    with pytest.raises(ValueError, match="unknown"):
        audit_holdout(changed)
    changed = copy.deepcopy(result)
    changed["records"][0]["runtime"][0]["output"] = "owned wrong output"
    with pytest.raises(ValueError, match="native boundary oracle"):
        audit_holdout(changed)
