"""Owned, non-timing native comparisons for primitive supplier-call preconditions."""
import gettext

import pytest

from msgbranch.project import audit_project


def observe(tmp_path, expression, mode):
    source = 'def render():\n    return gettext("%x") % ' + expression + '\n'
    app = tmp_path / "owned.py"
    app.write_text(source, encoding="utf-8")
    po = tmp_path / "empty.po"
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n',
                  encoding="utf-8")
    report = audit_project(app, [po], max_count=2, analysis_mode=mode)
    namespace = {"__builtins__": {}, "gettext": gettext.NullTranslations().gettext,
                 "bool": bool, "len": len}
    exec(compile(source, "<owned-builtin-regression>", "exec"), namespace)
    return report["findings"][0], namespace["render"]


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("expression,error", [
    ("bool(1 // 0)", ZeroDivisionError),
    ("len(1)", TypeError),
    ("len(None)", TypeError),
    ("len([1 // 0])", ZeroDivisionError),
    ("bool([1 // 0])", ZeroDivisionError),
    ("len({'x': 1 // 0, 'x': 1})", ZeroDivisionError),
    ("bool({'x': 1 // 0, 'x': 1})", ZeroDivisionError),
    ("bool(1, 2)", TypeError),
    ("bool(x=1)", TypeError),
    ("len('a', 'b')", TypeError),
    ("len(obj='a')", TypeError),
])
def test_failed_or_unresolved_builtin_argument_is_not_clean(tmp_path, mode, expression, error):
    finding, native = observe(tmp_path, expression, mode)
    with pytest.raises(error):
        native()
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("expression", [
    "bool(0)", "bool(1)", "bool(None)", "bool([])", "bool([1, 2])",
    "len('Ada')", "len([])", "len([1, None])", "len({'x': (1, 2)})",
])
def test_proven_owned_primitive_and_container_calls_remain_clean(tmp_path, expression):
    finding, native = observe(tmp_path, expression, "flow")
    assert isinstance(native(), str)
    assert finding["status"] == "clean"


@pytest.mark.parametrize("value", [0, 1])
def test_boolean_conversion_binding_can_be_used_as_a_local_condition(tmp_path, value):
    app = tmp_path / "condition.py"
    app.write_text('def render():\n'
                   f'    flag = bool({value})\n'
                   '    msg = gettext("%x")\n'
                   '    if flag:\n        args = 1\n'
                   '    else:\n        args = 2\n'
                   '    return msg % args\n', encoding="utf-8")
    po = tmp_path / "empty.po"
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n',
                  encoding="utf-8")
    report = audit_project(app, [po], max_count=2, analysis_mode="flow")
    assert report["findings"][0]["status"] == "clean"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("expression,error", [
    ("len(1)", TypeError),
    ("bool(1 // 0)", ZeroDivisionError),
    ("bool(not (1 // 0))", ZeroDivisionError),
    ("bool((1 // 0) < 2)", ZeroDivisionError),
    ("bool(f'{1 // 0}')", ZeroDivisionError),
    ("bool(f'{1:bad}')", ValueError),
])
@pytest.mark.parametrize("shape", ["tuple", "mapping", "keyword"])
def test_nested_supplier_preserves_evaluation_preconditions(tmp_path, mode, expression, error, shape):
    operation = {
        "tuple": 'gettext("%x") % (' + expression + ',)',
        "mapping": 'gettext("%(x)x") % {"x": ' + expression + '}',
        "keyword": 'gettext("{x:x}").format(x=' + expression + ')',
    }[shape]
    source = 'def render():\n    return ' + operation + '\n'
    app, po = tmp_path / "nested.py", tmp_path / "empty.po"
    app.write_text(source, encoding="utf-8")
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n', encoding="utf-8")
    namespace = {"__builtins__": {}, "gettext": gettext.NullTranslations().gettext,
                 "bool": bool, "len": len}
    exec(compile(source, "<owned-nested-supplier>", "exec"), namespace)
    with pytest.raises(error):
        namespace["render"]()
    finding = audit_project(app, [po], max_count=2, analysis_mode=mode)["findings"][0]
    assert finding["status"] != "clean"


@pytest.mark.parametrize("expression", ["bool(0)", "len('Ada')", "bool(not 0)"])
def test_closed_nested_suppliers_keep_flow_qualification(tmp_path, expression):
    source = 'def render():\n    return gettext("%x") % (' + expression + ',)\n'
    app, po = tmp_path / "closed.py", tmp_path / "empty.po"
    app.write_text(source, encoding="utf-8")
    po.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n', encoding="utf-8")
    assert audit_project(app, [po], max_count=2, analysis_mode="flow")["findings"][0]["status"] == "clean"
