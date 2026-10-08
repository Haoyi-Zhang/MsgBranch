from scripts.project_scaling import evaluate


def test_project_scaling_preserves_cache_and_classification():
    result = evaluate(sizes=(400,), repeats=1)
    records = {(row["shape"], row["calls"]): row for row in result["records"]}
    repeated = records[("repeated-message", 400)]
    unique = records[("unique-message", 400)]
    assert repeated["runtime_lookup_sets"] == 1
    assert repeated["cache_hits"] == 399
    assert unique["runtime_lookup_sets"] == 400
    assert unique["cache_hits"] == 0
    assert repeated["errors"] == unique["errors"] == 0
    assert repeated["unknown"] == unique["unknown"] == 0
