"""Tiny owned correctness fixtures; no upstream code or resource stress inputs."""
import ast
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po

from msgbranch import project
from msgbranch.program import Unsupported
from msgbranch.runtime import CatalogRuntime


PATTERN = "%(n)d item"
PLURAL = "%(n)d items"


def fixture(tmp_path, statement=None, *, source=None):
    if source is None:
        source = ('def render(n: int, supplied):\n'
                  '    args = {"n": n}\n'
                  '    spare = {"n": n}\n'
                  f'    {statement}\n'
                  f'    return ngettext({PATTERN!r}, {PLURAL!r}, n) % args\n')
    app = tmp_path / "app.py"
    app.write_text(source, encoding="utf-8")
    catalog = Catalog(locale="en")
    catalog.add((PATTERN, PLURAL), (PATTERN, PLURAL))
    catalog.add("ready", "ready")
    data = BytesIO()
    write_po(data, catalog)
    po = tmp_path / "messages.po"
    po.write_bytes(data.getvalue())
    return app, po


def native(app, po, n=2):
    runtime = CatalogRuntime(po)
    namespace = {"__builtins__": {}, "int": int, "ngettext": runtime.ngettext}
    # Only the source authored in fixture() above is executed here.
    exec(compile(app.read_text(encoding="utf-8"), "<owned-tiny-fixture>", "exec"), namespace)
    try:
        return "clean", namespace["render"](n, ({}, 0))
    except (KeyError, TypeError, ValueError) as exc:
        return "error", type(exc).__name__


INVALID_UNPACKS = [
    'args, spare = ({}, 0) if n == 2 else ({"n": n}, 0)',
    '[args, spare] = ({}, 0) if n == 2 else ({"n": n}, 0)',
    'args, spare = supplied',
    '(args, (spare, other)) = supplied',
    'args, *spare = ({}, 0)',
    'spare, *args = (0, {})',
    '(spare, (*args,)) = (0, ({},))',
    'args, spare = (*supplied,)',
    'args, (spare, other) = ({}, (0,))',
]


@pytest.mark.parametrize("statement", INVALID_UNPACKS)
def test_unmodeled_unpack_never_retains_old_clean_supplier(tmp_path, statement):
    app, po = fixture(tmp_path, statement)
    report = project.audit_project(app, [po], max_count=2)
    assert report["summary"]["clean"] == 0
    assert report["findings"][0]["status"] == "unknown"
    assert native(app, po)[0] == "error"


@pytest.mark.parametrize("statement", [
    'args, spare = ({"n": n}, 0)',
    '[args, spare] = [{"n": n}, 0]',
    '(spare, (args, other)) = (0, ({"n": n}, 0))',
])
def test_exact_equal_length_unpack_keeps_precision(tmp_path, statement):
    app, po = fixture(tmp_path, statement)
    report = project.audit_project(app, [po], max_count=2)
    assert report["summary"]["clean"] == 1
    assert report["summary"]["unknown"] == report["summary"]["errors"] == 0
    assert native(app, po) == ("clean", "2 items")


def cli(app, po):
    return subprocess.run(
        [sys.executable, "-B", "-m", "msgbranch.project", str(app), str(po), "--max-count", "2"],
        cwd=app.parent, capture_output=True, text=True, check=False,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=20,
    )


@pytest.mark.parametrize("statement,code", [
    (INVALID_UNPACKS[0], 2),
    (INVALID_UNPACKS[2], 2),
    (INVALID_UNPACKS[4], 2),
    ('args, spare = ({"n": n}, 0)', 0),
])
def test_real_cli_unpack_status(tmp_path, statement, code):
    app, po = fixture(tmp_path, statement)
    result = cli(app, po)
    assert result.returncode == code, result.stdout + result.stderr
    summary = json.loads(result.stdout)["summary"]
    assert summary["clean"] == (1 if code == 0 else 0)
    assert summary["unknown"] == (0 if code == 0 else 1)


@pytest.mark.parametrize("mode", ["direct", "flow"])
def test_admitted_file_is_parsed_once(tmp_path, monkeypatch, mode):
    app, po = fixture(tmp_path, source='gettext("ready")\n')
    real_parse = ast.parse
    calls = []

    def parsed(*args, **kwargs):
        calls.append(kwargs.get("filename"))
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(project.ast, "parse", parsed)
    assert project.audit_project(app, [po], max_count=2, analysis_mode=mode)["summary"]["clean"] == 1
    assert calls == [app.name]


@pytest.mark.parametrize("limit,parse_count", [("_MAX_SOURCE_BYTES", 0), ("_MAX_AST_NODES", 1)])
@pytest.mark.parametrize("mode", ["direct", "flow"])
def test_mocked_small_gate_skips_flow(tmp_path, monkeypatch, limit, parse_count, mode):
    app, po = fixture(tmp_path, 'args, spare = ({"n": n}, 0)')
    monkeypatch.setattr(project, limit, 1)
    real_parse = ast.parse
    calls = []

    def parsed(*args, **kwargs):
        calls.append(1)
        return real_parse(*args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("rejected input entered flow recovery")

    monkeypatch.setattr(project.ast, "parse", parsed)
    monkeypatch.setattr(project._FlowScanner, "scan", forbidden)
    monkeypatch.setattr(project, "_recover_flow_models", forbidden)
    report = project.audit_project(app, [po], max_count=2, analysis_mode=mode)
    assert report["summary"]["unknown"] == 1 and report["summary"]["clean"] == 0
    assert report["summary"]["flow_models"] == 0
    assert len(calls) == parse_count
    assert "budget" in report["findings"][0]["reason"]
    assert project.scan_source(app.read_text(encoding="utf-8"), app.name)[0].status == "unknown"


@pytest.mark.parametrize("limit", ["_MAX_SOURCE_BYTES", "_MAX_AST_NODES"])
def test_gate_exact_boundary_with_tiny_source(tmp_path, monkeypatch, limit):
    source = 'gettext("ready")\n# owned UTF-8: é\n'
    exact = len(source.encode("utf-8")) if limit == "_MAX_SOURCE_BYTES" else len(list(ast.walk(ast.parse(source))))
    monkeypatch.setattr(project, limit, exact)
    assert project.scan_source(source, "tiny.py")[0].status == "literal"
    monkeypatch.setattr(project, limit, exact - 1)
    assert project.scan_source(source, "tiny.py")[0].status == "unknown"


def test_recursive_invalidation_reaches_every_target_name():
    target = ast.parse('args, (spare, *other) = supplied').body[0].targets[0]
    scanner = project._FlowScanner(singulars=set(), plurals=set(), overloaded=set(),
                                   contextual_singulars=set(), contextual_plurals=set())
    env = {name: project._MappingValue((("n", project._Primitive("int", 2, True)),))
           for name in ("args", "spare", "other")}
    scanner._bind(target, project._Primitive("unknown"), env)
    assert all(isinstance(env[name], project._Unknown) for name in env)


@pytest.mark.parametrize("failure", [SyntaxError, RecursionError, MemoryError, Unsupported])
@pytest.mark.parametrize("mode", ["direct", "flow"])
def test_instrumented_parse_failure_is_unknown(tmp_path, monkeypatch, failure, mode):
    app, po = fixture(tmp_path, source='gettext("ready")\n')
    calls = []

    def failed(*args, **kwargs):
        calls.append(1)
        raise failure("owned injected parse failure")

    monkeypatch.setattr(project.ast, "parse", failed)
    report = project.audit_project(app, [po], max_count=2, analysis_mode=mode)
    assert report["summary"]["unknown"] == 1 and report["summary"]["clean"] == 0
    assert len(calls) == 1
    assert "owned injected parse failure" in report["findings"][0]["reason"]
    assert project.scan_source('gettext("ready")', app.name)[0].status == "unknown"


@pytest.mark.parametrize("failure", [RecursionError, MemoryError, Unsupported])
def test_scanner_failure_cannot_fall_back_to_direct_clean(tmp_path, monkeypatch, failure):
    app, po = fixture(tmp_path, source='gettext("ready")\n')

    def failed(*args, **kwargs):
        raise failure("owned injected scanner failure")

    monkeypatch.setattr(project._FlowScanner, "scan", failed)
    report = project.audit_project(app, [po], max_count=2)
    assert report["summary"]["unknown"] == 1 and report["summary"]["clean"] == 0
    assert "owned injected scanner failure" in report["findings"][0]["reason"]
    assert project.audit_project(app, [po], max_count=2, analysis_mode="direct")["summary"]["clean"] == 1


@pytest.mark.parametrize("failure", [RecursionError, MemoryError, Unsupported])
def test_witness_resolution_failure_is_unknown(tmp_path, monkeypatch, failure):
    app, po = fixture(tmp_path, source='gettext("ready")\n')

    def failed(*args, **kwargs):
        raise failure("owned injected witness failure")

    monkeypatch.setattr(project, "_flow_resolution", failed)
    report = project.audit_project(app, [po], max_count=2)
    assert report["summary"]["unknown"] == 1 and report["summary"]["clean"] == 0
    assert all(w["qualification"]["status"] == "unknown" for w in report["findings"][0]["witnesses"])


def test_cli_scanner_failure_has_diagnostic_exit(tmp_path, monkeypatch, capsys):
    app, po = fixture(tmp_path, source='gettext("ready")\n')

    def failed(*args, **kwargs):
        raise RecursionError("owned CLI injection")

    monkeypatch.setattr(project._FlowScanner, "scan", failed)
    monkeypatch.setattr(sys, "argv", ["msgbranch-project", str(app), str(po), "--max-count", "2"])
    with pytest.raises(SystemExit) as result:
        project.main()
    assert result.value.code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["unknown"] == 1


def test_exported_guard_rejects_unpack_regression(tmp_path, monkeypatch, capsys):
    app, po = fixture(tmp_path, 'args, spare = ({"n": n}, 0)')
    guard = tmp_path / "test_guard.py"
    monkeypatch.setattr(sys, "argv", ["msgbranch-project", str(app), str(po), "--max-count", "2",
                                     "--emit-pytest", str(guard)])
    with pytest.raises(SystemExit) as result:
        project.main()
    assert result.value.code == 0
    capsys.readouterr()
    namespace = {}
    exec(compile(guard.read_text(encoding="utf-8"), str(guard), "exec"), namespace)
    namespace["test_localized_message_boundaries"]()
    app.write_text(app.read_text(encoding="utf-8").replace('args, spare = ({"n": n}, 0)',
                                                         INVALID_UNPACKS[0]), encoding="utf-8")
    with pytest.raises(AssertionError):
        namespace["test_localized_message_boundaries"]()
