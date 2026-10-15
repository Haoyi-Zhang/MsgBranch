"""Portable eight-control helper checks, without running optional GNU msgfmt."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "gnu_msgfmt_contracts.py"
spec = importlib.util.spec_from_file_location("gnu_msgfmt_contracts_under_test", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ANALYZER_STATUS = {
    "named-reorder": "clean",
    "missing-caller-key": "error",
    "wrong-caller-type": "error",
    "catalog-field-mismatch": "error",
    "brace-precision": "clean",
    "bad-caller-precision": "unknown",
    "branch-specific-omission": "clean",
    "literal-percent": "clean",
}
EXPECTED_OUTPUT = {
    "named-reorder": "2 items for Ada",
    "brace-precision": "1.25",
    "branch-specific-omission": "un article",
    "literal-percent": "rate: 100%",
}


@pytest.mark.parametrize("case", module.controls(), ids=lambda case: case["id"])
def test_same_literal_caller_values_and_format_obligations(tmp_path, case):
    # Any accidental compiler/installation subprocess fails the unit test.
    with patch.object(module.subprocess, "run", side_effect=AssertionError("No GNU invocation in unit tests")) as run:
        po, app = tmp_path / "messages.po", tmp_path / "owned.py"
        po.write_bytes(module.po_bytes(case))
        source = module.caller_source(case)
        app.write_text(source, encoding="utf-8")
        runtime = module.CatalogRuntime(po)
        observed = module.native_outcome(case, runtime.translator)
        assert observed["status"] == case["expected_native"]
        namespace = {"__builtins__": {}, "gettext": runtime.translator.gettext,
                     "ngettext": runtime.translator.ngettext}
        exec(compile(source, "<owned-same-contract-unit>", "exec"), namespace)
        try:
            value, native_status = namespace["render"](), "PASS"
        except (TypeError, ValueError, KeyError) as exc:
            value, native_status = None, type(exc).__name__
        assert native_status == observed["status"]
        if native_status == "PASS":
            assert value == observed["output"] == EXPECTED_OUTPUT[case["id"]]
        report = module.audit_project(app, [po], max_count=2, analysis_mode="flow")
        assert len(report["findings"]) == 1
        assert report["findings"][0]["status"] == ANALYZER_STATUS[case["id"]]
        run.assert_not_called()
