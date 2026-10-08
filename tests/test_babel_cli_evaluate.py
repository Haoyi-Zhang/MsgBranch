from scripts.babel_cli_evaluate import evaluate


def test_babel_cli_compiles_frozen_catalogs_and_rejects_syntax_error():
    result = evaluate()
    assert result["status"] == "executed"
    summary = result["summary"]
    assert summary["catalogs"] >= 20
    assert summary['format_diagnostics_agree'] is True
    assert summary['all_outputs_equal'] == summary['catalogs'], [
        row for row in result['catalogs'] if not row.get('functional_equal_to_in_process')]
    assert summary["functional_equal"] == summary["cli_success"]
    assert summary["format_mismatch_rejected"] is True
    assert summary["invalid_encoding_rejected"] is True
