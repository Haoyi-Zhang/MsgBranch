"""Owned native controls for power evaluation and literal mapping construction."""
import gettext

import pytest

from msgbranch.project import audit_project


def observe(tmp_path, operation, mode, *, parameter=False, alias=False):
    source = "def render(" + ("base: int" if parameter else "") + "):\n"
    if alias:
        source += "    args = " + operation[0] + "\n"
        operation = operation[1]
    source += "    return " + operation + "\n"
    app, po = tmp_path / "owned.py", tmp_path / "empty.po"
    app.write_text(source, encoding="utf-8")
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n',
                  encoding="utf-8")
    namespace = {"__builtins__": {}, "gettext": gettext.NullTranslations().gettext,
                 "bool": bool, "len": len, "int": int}
    exec(compile(source, "<owned-power-mapping>", "exec"), namespace)
    finding = audit_project(app, [po], max_count=2, analysis_mode=mode)["findings"][0]
    return finding, namespace["render"]


def use(expression, shape):
    return {
        "scalar": 'gettext("%x") % ' + expression,
        "tuple": 'gettext("%x") % (' + expression + ',)',
        "mapping": 'gettext("%(x)x") % {"x": ' + expression + '}',
        "keyword": 'gettext("{x:x}").format(x=' + expression + ')',
        "format_map": 'gettext("{x:x}").format_map({"x": ' + expression + '})',
    }[shape]


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("shape", ["scalar", "tuple", "mapping", "keyword", "format_map"])
@pytest.mark.parametrize("expression,error", [
    ("bool(0 ** -1)", ZeroDivisionError),
    ("bool((10 ** 400) ** -1)", OverflowError),
])
def test_failed_negative_power_is_not_clean(tmp_path, mode, shape, expression, error):
    finding, native = observe(tmp_path, use(expression, shape), mode)
    with pytest.raises(error):
        native()
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("shape", ["scalar", "tuple", "mapping", "keyword", "format_map"])
@pytest.mark.parametrize("expression", ["bool(2 ** -1)", "bool((-2) ** -1)", "2 ** 3"])
def test_proven_integer_powers_remain_qualified(tmp_path, shape, expression):
    finding, native = observe(tmp_path, use(expression, shape), "flow")
    assert isinstance(native(), str)
    assert finding["status"] == "clean"


@pytest.mark.parametrize("shape", ["scalar", "tuple", "mapping", "keyword", "format_map"])
def test_negative_power_of_unresolved_base_remains_unknown(tmp_path, shape):
    finding, native = observe(tmp_path, use("bool(base ** -1)", shape), "flow", parameter=True)
    with pytest.raises(ZeroDivisionError):
        native(0)
    assert isinstance(native(2), str)
    assert finding["status"] == "unknown"


def mapping_use(expression, shape):
    return {
        "percent": 'gettext("%(x)x") % ' + expression,
        "format_map": 'gettext("{x:x}").format_map(' + expression + ')',
        "bool": 'gettext("%x") % bool(' + expression + ')',
        "len": 'gettext("%x") % len(' + expression + ')',
    }[shape]


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("shape", ["percent", "format_map", "bool", "len"])
@pytest.mark.parametrize("expression,error", [
    ("{'x': 1 // 0, 'x': 1}", ZeroDivisionError),
    ("{'x': int('bad'), 'x': 1}", ValueError),
])
def test_overwritten_failed_expression_is_still_evaluated(tmp_path, mode, shape, expression, error):
    finding, native = observe(tmp_path, mapping_use(expression, shape), mode)
    with pytest.raises(error):
        native()
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("shape", ["percent", "format_map"])
@pytest.mark.parametrize("expression,error", [
    ("{'x': 1 // 0, 'x': 1}", ZeroDivisionError),
    ("{'x': int('bad'), 'x': 1}", ValueError),
])
def test_local_mapping_alias_retains_overwritten_obligation(tmp_path, shape, expression, error):
    finding, native = observe(tmp_path, (expression, mapping_use("args", shape)), "flow", alias=True)
    with pytest.raises(error):
        native()
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("mode,shape", [("direct", "percent"), ("flow", "percent"), ("flow", "format_map")])
@pytest.mark.parametrize("expression,status", [
    ("{'x': 'wrong', 'x': 7}", "clean"),
    ("{'x': 7, 'x': 'wrong'}", "error"),
    ("{'x': 7, 'x': 1}", "clean"),
])
def test_qualified_duplicate_keys_keep_last_value(tmp_path, mode, shape, expression, status):
    finding, native = observe(tmp_path, mapping_use(expression, shape), mode)
    if status == "error":
        with pytest.raises((TypeError, ValueError)):
            native()
    else:
        assert isinstance(native(), str)
    assert finding["status"] == status


@pytest.mark.parametrize("expression", [
    "{'x': bool(0), 'x': 7}",
    "{'x': 2 ** -1, 'x': 7}",
])
def test_proven_discarded_scalar_keeps_mapping_qualification(tmp_path, expression):
    finding, native = observe(tmp_path, mapping_use(expression, "percent"), "flow")
    assert isinstance(native(), str)
    assert finding["status"] == "clean"
