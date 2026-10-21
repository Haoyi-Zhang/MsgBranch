"""Owned bounded native checks for supplier construction and its CI consumer."""
from io import BytesIO
import json
import subprocess
import sys

import pytest
from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po

from msgbranch.project import audit_project
from msgbranch.runtime import CatalogRuntime


SHAPES = {
    "percent-scalar": ("%x items", "msg % VALUE"),
    "percent-tuple": ("%x items", "msg % (VALUE,)"),
    "brace-positional": ("{0:x} items", "msg.format(VALUE)"),
    "brace-keyword": ("{x:x} items", "msg.format(x=VALUE)"),
}
DOMAIN = set(range(201))


def fixture(tmp_path, shape, expression, *, inline=False):
    pattern, operation = SHAPES[shape]
    source = ('def render(n: int):\n'
              f'    msg = ngettext({pattern!r}, {pattern!r}, n)\n')
    if not inline:
        source += f'    value = {expression}\n'
    source += '    return ' + operation.replace("VALUE", f"({expression})" if inline else "value") + '\n'
    app, po = tmp_path / "owned.py", tmp_path / "messages.po"
    app.write_text(source, encoding="utf-8")
    catalog = Catalog(locale="en")
    catalog.add((pattern, pattern), (pattern, pattern))
    data = BytesIO()
    write_po(data, catalog)
    po.write_bytes(data.getvalue())
    runtime = CatalogRuntime(po)
    namespace = {"__builtins__": {}, "int": int, "float": float, "ngettext": runtime.ngettext}
    exec(compile(source, "<owned-supplier-construction>", "exec"), namespace)
    return app, po, namespace["render"]


def classified_counts(report, status):
    counts = set()
    for witness in report["findings"][0]["witnesses"]:
        if witness["qualification"]["status"] == status:
            for low, high in witness["covered_count_ranges"]:
                counts.update(range(low, high + 1))
    return counts


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("inline", [False, True])
def test_count_conditioned_construction_failure_is_not_clean(tmp_path, shape, inline):
    app, po, native = fixture(tmp_path, shape, "n // (n - 100)", inline=inline)
    with pytest.raises(ZeroDivisionError):
        native(100)
    for n in DOMAIN - {100}:
        assert isinstance(native(n), str)
    report = audit_project(app, [po], max_count=200)
    # Evaluation is not modeled as a proven formatting incompatibility.
    assert report["summary"]["unknown"] == 1
    assert report["summary"]["errors"] == report["summary"]["clean"] == 0
    assert classified_counts(report, "unknown") == {100}
    assert classified_counts(report, "clean") == DOMAIN - {100}
    assert classified_counts(report, "error") == set()


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("expression", ["n // (n + 1)", "n + 1", "(n - 1) * 2"])
def test_proven_nonthrowing_arithmetic_remains_clean(tmp_path, shape, inline, expression):
    app, po, native = fixture(tmp_path, shape, expression, inline=inline)
    assert all(isinstance(native(n), str) for n in DOMAIN)
    report = audit_project(app, [po], max_count=200)
    assert report["summary"]["clean"] == 1
    assert classified_counts(report, "clean") == DOMAIN


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("expression", ['"bad"', "float(n)"])
def test_known_formatting_mismatch_remains_error(tmp_path, shape, expression):
    app, po, native = fixture(tmp_path, shape, expression)
    for n in (0, 1, 100, 200):
        with pytest.raises((TypeError, ValueError)):
            native(n)
    report = audit_project(app, [po], max_count=200)
    assert report["summary"]["errors"] == 1
    assert report["summary"]["unknown"] == report["summary"]["clean"] == 0
    assert classified_counts(report, "error") == DOMAIN


@pytest.mark.parametrize("shape", SHAPES)
def test_construction_unknown_does_not_hide_other_known_errors(tmp_path, shape):
    app, po, native = fixture(tmp_path, shape, '"bad" if n != 100 else n // (n - 100)')
    with pytest.raises(ZeroDivisionError):
        native(100)
    with pytest.raises((TypeError, ValueError)):
        native(1)
    report = audit_project(app, [po], max_count=200)
    assert report["summary"]["errors"] == 1
    assert classified_counts(report, "unknown") == {100}
    assert classified_counts(report, "error") == DOMAIN - {100}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("expression,expected_code", [
    ("n // (n - 100)", 2),
    ("n // (n + 1)", 0),
    ('"bad"', 1),
    ('"bad" if n != 100 else n // (n - 100)', 1),
])
def test_real_cli_and_emitted_guard_preserve_status(tmp_path, shape, expression, expected_code):
    app, po, _ = fixture(tmp_path, shape, expression)
    guard = tmp_path / "test_generated_guard.py"
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "msgbranch.project", str(app), str(po),
         "--max-count", "200", "--emit-pytest", str(guard)],
        text=True, capture_output=True, encoding="utf-8", timeout=20, check=False,
    )
    report = json.loads(completed.stdout)
    assert completed.returncode == expected_code, (completed.returncode, report.get("summary"), completed.stderr)
    assert report["summary"]["calls"] == 1
    namespace = {}
    exec(compile(guard.read_text(encoding="utf-8"), str(guard), "exec"), namespace)
    if expected_code:
        with pytest.raises(AssertionError):
            namespace["test_localized_message_boundaries"]()
    else:
        namespace["test_localized_message_boundaries"]()


@pytest.mark.parametrize("shape", SHAPES)
def test_guard_rejects_later_supplier_construction_regression(tmp_path, shape):
    app, po, _ = fixture(tmp_path, shape, "n // (n + 1)")
    guard = tmp_path / "test_generated_guard.py"
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "msgbranch.project", str(app), str(po),
         "--max-count", "200", "--emit-pytest", str(guard)],
        text=True, capture_output=True, encoding="utf-8", timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    namespace = {}
    exec(compile(guard.read_text(encoding="utf-8"), str(guard), "exec"), namespace)
    namespace["test_localized_message_boundaries"]()
    # Same call identity and catalog, now a failing supplier at count 100.
    _, _, native = fixture(tmp_path, shape, "n // (n - 100)")
    with pytest.raises(ZeroDivisionError):
        native(100)
    with pytest.raises(AssertionError):
        namespace["test_localized_message_boundaries"]()


@pytest.mark.parametrize("operation", [
    'gettext("{0:x}").format(7, 1 // 0)',
    'gettext("{x:x}").format(x=7, unused=1 // 0)',
    'gettext("%(x)x") % dict(x=7, unused=1 // 0)',
])
def test_unused_argument_construction_is_still_required(tmp_path, operation):
    app, po = tmp_path / "owned.py", tmp_path / "empty.po"
    source = 'def render():\n    return ' + operation + '\n'
    app.write_text(source, encoding="utf-8")
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n', encoding="utf-8")
    namespace = {"__builtins__": {}, "dict": dict, "gettext": CatalogRuntime(po).gettext}
    exec(compile(source, "<owned-unused-argument>", "exec"), namespace)
    with pytest.raises(ZeroDivisionError):
        namespace["render"]()
    assert audit_project(app, [po])["findings"][0]["status"] == "unknown"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("name", ["absent-project", "absent.py"])
@pytest.mark.parametrize("emit_guard", [False, True])
def test_missing_source_path_is_unavailable_not_empty_success(tmp_path, mode, name, emit_guard):
    missing, po = tmp_path / name, tmp_path / "empty.po"
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n', encoding="utf-8")
    assert not missing.exists()
    with pytest.raises((OSError, ValueError), match="source"):
        audit_project(missing, [po], analysis_mode=mode)
    guard, report = tmp_path / "test_guard.py", tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "msgbranch.project", str(missing), str(po),
         "--analysis-mode", mode, "--output", str(report),
         *(["--emit-pytest", str(guard)] if emit_guard else [])],
        text=True, capture_output=True, encoding="utf-8", timeout=20, check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    receipt = json.loads(report.read_text(encoding="utf-8"))
    assert receipt["status"] == "unavailable-or-unknown"
    assert "source" in receipt["error"]
    assert not guard.exists()


def test_existing_empty_project_keeps_empty_success_semantics(tmp_path):
    source, po = tmp_path / "empty-project", tmp_path / "empty.po"
    source.mkdir()
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n', encoding="utf-8")
    report = audit_project(source, [po])
    assert report["summary"]["python_files"] == 0
    assert report["summary"]["errors"] == report["summary"]["unknown"] == 0
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "msgbranch.project", str(source), str(po)],
        text=True, capture_output=True, encoding="utf-8", timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["summary"]["python_files"] == 0
