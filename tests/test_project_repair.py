"""Owned, benign temporary fixtures for bounded project qualification.

Only the source strings authored below are executed for native differentials.
Audited target source is never imported. No packaged upstream method is run.
"""
from io import BytesIO
from pathlib import Path
import os
import subprocess
import sys

import pytest
from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po

from msgbranch import project
from msgbranch.runtime import CatalogRuntime
from scripts import reproduce


def fixture(tmp_path, source, singular, plural=None):
    app = tmp_path / "app.py"
    app.write_text(source, encoding="utf-8")
    catalog = Catalog(locale="en")
    catalog.add((singular, plural) if plural is not None else singular,
                (singular, plural) if plural is not None else singular)
    out = BytesIO()
    write_po(out, catalog)
    po = tmp_path / "messages.po"
    po.write_bytes(out.getvalue())
    report = project.audit_project(app, [po], max_count=200)
    assert report["summary"]["calls"] == 1
    assert report["summary"]["findings"] == 1
    return app, po, report


def native(source, po, *args):
    runtime = CatalogRuntime(po)
    namespace = {"__builtins__": {}, "str": str, "int": int, "float": float, "bool": bool, "len": len,
                 "gettext": runtime.gettext, "ngettext": runtime.ngettext}
    exec(compile(source, "<owned-msgbranch-fixture>", "exec"), namespace)
    try:
        return "clean", namespace["render"](*args)
    except (TypeError, ValueError, KeyError, IndexError, OverflowError) as exc:
        return "error", type(exc).__name__


def counts(report, status):
    result = set()
    for witness in report["findings"][0]["witnesses"]:
        if witness["qualification"]["status"] == status:
            for low, high in witness["covered_count_ranges"]:
                if low is not None:
                    result.update(range(low, high + 1))
    return result


@pytest.mark.parametrize("expression,failures", [
    ("(n == 100 and 'bad') or n", {100}),
    ("n == 100 and 'bad'", {100}),
    ("n or 'bad'", {0}),
    ("n == 100 or n", set()),
])
def test_bool_operands_match_native_at_every_bounded_count(tmp_path, expression, failures):
    source = ('def render(n: int):\n'
              '    msg = ngettext("%d item", "%d items", n)\n'
              f'    value = {expression}\n'
              '    return msg % value\n')
    _, po, report = fixture(tmp_path, source, "%d item", "%d items")
    actual = {n for n in range(201) if native(source, po, n)[0] == "error"}
    assert actual == failures
    assert counts(report, "error") == actual
    assert counts(report, "clean") == set(range(201)) - actual
    assert report["summary"]["unknown"] == 0


def test_direct_bool_supplier_is_not_inferred_as_bool(tmp_path):
    source = 'def render(n: int):\n    return ngettext("%d", "%d", n) % ((n == 100 and "bad") or n)\n'
    app, po, _ = fixture(tmp_path, source, "%d", "%d")
    direct = project.audit_project(app, [po], analysis_mode="direct")
    assert direct["summary"]["unknown"] == 1
    assert direct["summary"]["clean"] == 0


def test_unresolved_bool_operand_in_named_supplier_remains_unknown(tmp_path):
    source = ('def render(flag):\n    msg = gettext("%(owner)s")\n'
              '    value = (flag and "Ada") or unresolved()\n'
              '    return msg % {"owner": value}\n')
    _, _, report = fixture(tmp_path, source, "%(owner)s")
    assert report["summary"]["unknown"] == 1
    assert report["summary"]["clean"] == 0


@pytest.mark.parametrize("statement", [
    'if args.pop("owner"):\n        pass',
    'if len(args.pop("owner")):\n        pass',
    'value = f"{args.pop(\"owner\")}"',
    'value = args.pop("owner") == "Ada"',
    'value = args.pop("owner") and True',
    'value = bool(args.pop("owner"))',
    'value = str(args.pop("owner"))',
    'value = True if args.pop("owner") else False',
    'alias = args\n    if alias.pop("owner"):\n        pass',
    'assert args.pop("owner")',
    'other = {"Ada": 1}\n    del other[args.pop("owner")]',
    'other = {}\n    other[args.pop("owner")] = 1',
    'other = {"Ada": 1}\n    other[args.pop("owner")] += 1',
])
def test_evaluated_child_mutations_taint_supplier(tmp_path, statement):
    source = ('def render():\n    msg = gettext("%(owner)s")\n'
              '    args = {"owner": "Ada"}\n    ' + statement + '\n    return msg % args\n')
    _, po, report = fixture(tmp_path, source, "%(owner)s")
    assert native(source, po) == ("error", "KeyError")
    assert report["summary"]["clean"] == 0
    assert report["summary"]["unknown"] == 1


@pytest.mark.parametrize("expression", ['False and args.pop("owner")', 'True or args.pop("owner")'])
def test_constant_short_circuit_does_not_evaluate_mutation(tmp_path, expression):
    source = ('def render():\n    msg = gettext("%(owner)s")\n'
              '    args = {"owner": "Ada"}\n'
              f'    value = {expression}\n    return msg % args\n')
    _, po, report = fixture(tmp_path, source, "%(owner)s")
    assert native(source, po) == ("clean", "Ada")
    assert report["summary"]["clean"] == 1


def test_count_short_circuit_effect_is_unknown_only_where_evaluated(tmp_path):
    source = ('def render(n: int):\n    msg = ngettext("%(owner)s", "%(owner)s many", n)\n'
              '    args = {"owner": "Ada"}\n'
              '    value = n == 100 and args.pop("owner")\n'
              '    return msg % args\n')
    _, po, report = fixture(tmp_path, source, "%(owner)s", "%(owner)s many")
    assert {n for n in range(201) if native(source, po, n)[0] == "error"} == {100}
    assert counts(report, "unknown") == {100}
    assert counts(report, "clean") == set(range(201)) - {100}


@pytest.mark.parametrize("body", [
    'if n == 1:\n        return ngettext("one", "%(owner)s many", n) % {}\n    return "skip"',
    'if n != 1:\n        return "skip"\n    return ngettext("one", "%(owner)s many", n) % {}',
    'if n < 2:\n        if n != 0:\n            return ngettext("one", "%(owner)s many", n) % {}\n    return "skip"',
])
def test_guarded_lookup_filters_unreachable_counts(tmp_path, body):
    source = 'def render(n: int):\n    ' + body + '\n'
    _, po, report = fixture(tmp_path, source, "one", "%(owner)s many")
    assert all(native(source, po, n)[0] == "clean" for n in range(201))
    assert report["summary"]["clean"] == 1
    witnesses = report["findings"][0]["witnesses"]
    assert len(witnesses) == 1
    assert witnesses[0]["covered_count_ranges"] == [[1, 1]]
    assert report["findings"][0]["unreachable_count_ranges"] == [[0, 0], [2, 200]]


def test_terminated_use_is_not_falsely_certified_or_reported_error(tmp_path):
    source = ('def render(n: int):\n    return "skip"\n'
              '    return ngettext("one", "%(owner)s many", n) % {}\n')
    _, po, report = fixture(tmp_path, source, "one", "%(owner)s many")
    assert all(native(source, po, n) == ("clean", "skip") for n in range(201))
    assert report["summary"]["errors"] == report["summary"]["clean"] == 0
    assert report["summary"]["unknown"] == 1
    assert report["summary"]["selected_patterns"] == 0


def test_unresolved_reachability_is_unknown_not_definite_error(tmp_path):
    source = ('def render(n: int, flag):\n    if flag:\n'
              '        return ngettext("one", "%(owner)s many", n) % {}\n    return "skip"\n')
    _, _, report = fixture(tmp_path, source, "one", "%(owner)s many")
    assert report["summary"]["unknown"] == 1
    assert report["summary"]["errors"] == report["summary"]["clean"] == 0


@pytest.mark.parametrize("pattern,expression,status,detail", [
    ("%d", 'gettext("%d") % (1, 2)', "error", "TypeError"),
    ("{x!s:d}", 'gettext("{x!s:d}").format(x=1)', "error", "ValueError"),
    ("{x!r:d}", 'gettext("{x!r:d}").format(x=1)', "error", "ValueError"),
    ("{x!a:f}", 'gettext("{x!a:f}").format(x=1)', "error", "ValueError"),
    ("%d", 'gettext("%d") % 1.25', "clean", "1"),
    ("%i", 'gettext("%i") % 1.25', "clean", "1"),
    ("%u", 'gettext("%u") % 1.25', "clean", "1"),
    ("%x", 'gettext("%x") % 1.25', "error", "TypeError"),
    ("%o", 'gettext("%o") % 1.25', "error", "TypeError"),
    ("{x:d}", 'gettext("{x:d}").format(x=1.25)', "error", "ValueError"),
    ("{x!s:>4}", 'gettext("{x!s:>4}").format(x=1)', "clean", "   1"),
    ("%(x)d", 'gettext("%(x)d") % {"x": 1.25, "unused": "safe"}', "clean", "1"),
    ("{0:d}", 'gettext("{0:d}").format(1, 2)', "clean", "1"),
])
def test_primitive_formatting_matches_native(tmp_path, pattern, expression, status, detail):
    source = 'def render():\n    return ' + expression + '\n'
    _, po, report = fixture(tmp_path, source, pattern)
    assert native(source, po) == (status, detail)
    assert report["findings"][0]["status"] == status
    assert report["summary"]["selected_patterns"] == 1


def test_unresolved_float_decimal_coercion_remains_unknown(tmp_path):
    source = 'def render(x: float):\n    return gettext("%d") % x\n'
    _, po, report = fixture(tmp_path, source, "%d")
    assert native(source, po, 1.25) == ("clean", "1")
    assert native(source, po, float("inf")) == ("error", "OverflowError")
    assert report["summary"]["unknown"] == 1


def test_unsupported_brace_conversion_remains_unknown(tmp_path):
    source = 'def render():\n    return gettext("{x!z}").format(x=1)\n'
    _, po, report = fixture(tmp_path, source, "{x!z}")
    assert native(source, po) == ("error", "ValueError")
    assert report["summary"]["unknown"] == 1


def emit_guard(monkeypatch, capsys, app, po, guard, *options):
    monkeypatch.setattr(sys, "argv", ["msgbranch-project", str(app), str(po),
                                     "--max-count", "2", "--emit-pytest", str(guard), *options])
    with pytest.raises(SystemExit) as exit_info:
        project.main()
    capsys.readouterr()
    return exit_info.value.code


def run_guard(guard):
    namespace = {}
    exec(compile(guard.read_text(encoding="utf-8"), str(guard), "exec"), namespace)
    namespace["test_localized_message_boundaries"]()


@pytest.mark.parametrize("analysis_mode", ["flow", "direct"])
def test_generated_guard_preserves_all_wrapper_lists_and_executes(tmp_path, monkeypatch, capsys, analysis_mode):
    app = tmp_path / "app.py"
    app.write_text('def render(n: int):\n'
                   '    a = tr("safe")\n'
                   '    b = trs("one", "many", n)\n'
                   '    c = ctr("ctx", "safe")\n'
                   '    d = ctrs("ctx", "one", "many", n)\n'
                   '    e = flex("safe")\n'
                   '    f = flex("one", "many", n)\n'
                   '    return a, b, c, d, e, f\n', encoding="utf-8")
    catalog = Catalog(locale="en")
    for context in (None, "ctx"):
        catalog.add("safe", "safe", context=context)
        catalog.add(("one", "many"), ("one", "many"), context=context)
    out = BytesIO()
    write_po(out, catalog)
    po = tmp_path / "messages.po"
    po.write_bytes(out.getvalue())
    guard = tmp_path / "test_guard.py"
    options = ("--singular-callee", "tr", "--plural-callee", "trs",
               "--contextual-singular-callee", "ctr", "--contextual-plural-callee", "ctrs",
               "--overloaded-callee", "flex", "--require-catalog", "--analysis-mode", analysis_mode)
    assert emit_guard(monkeypatch, capsys, app, po, guard, *options) == 0
    actual_audit = project.audit_project
    calls = []
    def observed(*args, **kwargs):
        result = actual_audit(*args, **kwargs)
        calls.append((kwargs, result["summary"]))
        return result
    monkeypatch.setattr(project, "audit_project", observed)
    run_guard(guard)
    assert len(calls) == 1
    config, summary = calls[0]
    assert summary["calls"] == summary["clean"] == 6
    assert summary["selected_patterns"] == 9
    for field, name in (("singular_callees", "tr"), ("plural_callees", "trs"),
                        ("contextual_singular_callees", "ctr"), ("contextual_plural_callees", "ctrs"),
                        ("overloaded_callees", "flex")):
        assert name in config[field]
    assert config["max_count"] == 2 and config["require_catalog"] is True
    assert config["analysis_mode"] == analysis_mode
    # Other recognized calls remain: losing only one wrapper must still fail.
    app.write_text(app.read_text(encoding="utf-8").replace('tr("safe")', 'lost("safe")'), encoding="utf-8")
    with pytest.raises(AssertionError, match="boundary recognition lost"):
        run_guard(guard)
    # A zero-call analysis cannot pass this previously nonempty guard.
    app.write_text('def render():\n    return "safe"\n', encoding="utf-8")
    with pytest.raises(AssertionError, match="boundary recognition lost"):
        run_guard(guard)


def test_generated_custom_wrapper_guard_fails_real_qualification(tmp_path, monkeypatch, capsys):
    app, po, _ = fixture(tmp_path, 'def render():\n    return gettext("%(owner)s") % {}\n', "%(owner)s")
    app.write_text('def render():\n    return tr("%(owner)s") % {}\n', encoding="utf-8")
    guard = tmp_path / "test_guard.py"
    assert emit_guard(monkeypatch, capsys, app, po, guard, "--singular-callee", "tr") == 1
    with pytest.raises(AssertionError):
        run_guard(guard)


def test_no_recognized_boundary_cannot_emit_guard(tmp_path, monkeypatch, capsys):
    app, po, _ = fixture(tmp_path, 'def render():\n    return gettext("safe")\n', "safe")
    app.write_text('def render():\n    return "safe"\n', encoding="utf-8")
    guard = tmp_path / "test_guard.py"
    assert emit_guard(monkeypatch, capsys, app, po, guard) == 2
    assert not guard.exists()


def test_exported_guard_runs_in_pytest_and_fails_errors_and_zero_calls(tmp_path, monkeypatch, capsys):
    app, po, _ = fixture(tmp_path, 'def render():\n    return gettext("%(owner)s") % {"owner": "Ada"}\n', "%(owner)s")
    source = 'def render():\n    return tr("%(owner)s") % {"owner": "Ada"}\n'
    app.write_text(source, encoding="utf-8")
    guard = tmp_path / "test_exported_guard.py"
    assert emit_guard(monkeypatch, capsys, app, po, guard, "--singular-callee", "tr") == 0
    def run():
        return subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "--rootdir", str(tmp_path), str(guard)],
                              cwd=tmp_path, capture_output=True, text=True, check=False,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"))
    clean = run()
    assert clean.returncode == 0 and "1 passed" in clean.stdout, clean.stdout + clean.stderr
    app.write_text(source.replace('{"owner": "Ada"}', '{}'), encoding="utf-8")
    error = run()
    assert error.returncode == 1 and "1 failed" in error.stdout, error.stdout + error.stderr
    app.write_text('def render():\n    return "safe"\n', encoding="utf-8")
    zero = run()
    assert zero.returncode == 1 and "boundary recognition lost" in zero.stdout, zero.stdout + zero.stderr


@pytest.mark.parametrize("full", [False, True])
def test_portable_driver_runs_checked_unit_stage_first(monkeypatch, full):
    calls = []
    def mocked_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(reproduce.subprocess, "run", mocked_run)
    monkeypatch.setattr(sys, "argv", ["reproduce.py", *( ["--full"] if full else [])])
    reproduce.main()
    assert calls[0][0] == [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    assert all(options["check"] is True for _, options in calls)
    assert len(calls) > 1
    assert any("partition_evaluate.py" in str(command[-1]) for command, _ in calls) is full


def test_portable_driver_stops_when_unit_stage_fails(monkeypatch):
    calls = []
    def mocked_run(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(reproduce.subprocess, "run", mocked_run)
    monkeypatch.setattr(sys, "argv", ["reproduce.py"])
    with pytest.raises(subprocess.CalledProcessError):
        reproduce.main()
    assert len(calls) == 1 and calls[0][1:3] == ["-m", "pytest"]
