"""Owned local fixtures for mutation, lookup-origin and format qualification.

Only the short source strings authored in this file are executed for native
comparisons. No upstream application, study driver or target module is imported.
"""
import gettext
from io import BytesIO

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
import pytest

from msgbranch.project import audit_project
from msgbranch.runtime import CatalogRuntime


def _fixture(tmp_path, source, pattern, *, mode="flow", require_catalog=False, first=None):
    app = tmp_path / "app.py"
    app.write_text(source, encoding="utf-8")
    catalog = Catalog(locale="en")
    if first is None:
        catalog.add(pattern, pattern)
    else:
        catalog.add(("Open", "Opens"), (first, "Ouvrir"), context="menu")
        # A different context must not supply the provenance of the tested slot.
        catalog.add(("Open", "Opens"), ("Other", "Others"), context="other")
    data = BytesIO()
    write_po(data, catalog)
    po = tmp_path / "messages.po"
    po.write_bytes(data.getvalue())
    report = audit_project(app, [po], max_count=2, analysis_mode=mode,
                           require_catalog=require_catalog)
    assert report["summary"]["calls"] == report["summary"]["findings"] == 1
    return po, report["findings"][0]


def _native(source, po, *args):
    # Direct GNUTranslations lookup, not the adapter's provenance annotation.
    translation = gettext.GNUTranslations(BytesIO(CatalogRuntime(po).mo))
    namespace = {"__builtins__": {}, "int": int, "gettext": translation.gettext,
                 "pgettext": translation.pgettext}
    exec(compile(source, "<owned-qualification-regression>", "exec"), namespace)
    return namespace["render"](*args)


@pytest.mark.parametrize("target", ["args", "alias"])
def test_augmented_dictionary_update_invalidates_old_alias(tmp_path, target):
    source = ('def render():\n'
              '    msg = gettext("%(x)d")\n'
              '    args = {"x": 1}\n'
              '    alias = args\n'
              f'    {target} |= {{"x": "bad"}}\n'
              '    return msg % alias\n')
    po, finding = _fixture(tmp_path, source, "%(x)d")
    with pytest.raises(TypeError):
        _native(source, po)
    assert finding["status"] == "unknown"
    assert all(w["qualification"]["status"] == "unknown" for w in finding["witnesses"])


@pytest.mark.parametrize("outer,access", [
    ('{"args": args}', 'box["args"]'),
    ('[args]', 'box[0]'),
    ('(args,)', 'box[0]'),
    ('{"wrapped": (args,)}', 'box["wrapped"][0]'),
])
def test_unresolved_outer_escape_invalidates_nested_mutable_alias(tmp_path, outer, access):
    source = ('def corrupt(box):\n'
              f'    {access}.clear()\n'
              'def render():\n'
              '    msg = gettext("%(owner)s")\n'
              '    args = {"owner": "Ada"}\n'
              '    alias = args\n'
              f'    box = {outer}\n'
              '    corrupt(box)\n'
              '    return msg % alias\n')
    po, finding = _fixture(tmp_path, source, "%(owner)s")
    with pytest.raises(KeyError):
        _native(source, po)
    assert finding["status"] == "unknown"


def test_simple_rebinding_does_not_invalidate_previous_object_alias(tmp_path):
    source = ('def render():\n'
              '    msg = gettext("%(x)d")\n'
              '    args = {"x": 1}\n'
              '    alias = args\n'
              '    args = {"x": "bad"}\n'
              '    return msg % alias\n')
    po, finding = _fixture(tmp_path, source, "%(x)d")
    assert _native(source, po) == "1"
    assert finding["status"] == "clean"


def test_escape_does_not_taint_distinct_equal_container(tmp_path):
    source = ('def corrupt(box):\n'
              '    box["args"].clear()\n'
              'def render():\n'
              '    msg = gettext("%(owner)s")\n'
              '    args = {"owner": "Ada"}\n'
              '    other = {"owner": "Ada"}\n'
              '    box = {"args": other}\n'
              '    corrupt(box)\n'
              '    return msg % args\n')
    po, finding = _fixture(tmp_path, source, "%(owner)s")
    assert _native(source, po) == "Ada"
    assert finding["status"] == "clean"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("require_catalog", [False, True])
@pytest.mark.parametrize("first", ["", "Ouvert"])
def test_contextual_plural_at_one_preserves_compiler_origin(tmp_path, mode, require_catalog, first):
    source = 'def render():\n    return pgettext("menu", "Open")\n'
    po, finding = _fixture(tmp_path, source, "Open", mode=mode,
                           require_catalog=require_catalog, first=first)
    native_output = _native(source, po)
    assert native_output == (first or "Open")
    runtime = CatalogRuntime(po)
    assert runtime.pgettext("menu", "Open") == native_output
    origin = "catalog-plural-at-one" if first else "compiler-source-substitution"
    assert runtime.trace[-1].resolution == origin
    assert finding["status"] == ("error" if require_catalog and not first else "clean")
    assert finding["witnesses"][0]["lookup"]["resolution"] == origin
    assert finding["witnesses"][0]["fallback"] is (not bool(first))
    if require_catalog and not first:
        assert finding["witnesses"][0]["qualification"]["reason"] == "catalog-presence obligation violated"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("expression", ["17", "1.25"])
@pytest.mark.parametrize("spec", ["n", ">8n", "+n"])
def test_locale_numeric_n_accepts_native_int_and_float(tmp_path, mode, expression, spec):
    pattern = "{x:" + spec + "}"
    source = f'def render():\n    return gettext({pattern!r}).format(x={expression})\n'
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    assert _native(source, po) == pattern.format(x=17 if expression == "17" else 1.25)
    assert finding["status"] == "clean"
    assert finding["witnesses"][0]["qualification"]["requirements"]["named_types"] == (("x", "number"),)


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("spec,expression", [
    ("+", '"Ada"'),
    ("q", '"Ada"'),
    ("qf", "1.25"),
    ("++d", "1"),
    (".2", "1"),
    ("+s", '"Ada"'),
])
def test_unmodeled_or_type_dependent_spec_is_unknown_not_clean(tmp_path, mode, spec, expression):
    pattern = "{x:" + spec + "}"
    source = f'def render():\n    return gettext({pattern!r}).format(x={expression})\n'
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    with pytest.raises(ValueError):
        _native(source, po)
    assert finding["status"] == "unknown"
    assert finding["witnesses"][0]["qualification"]["reason"] == "unmodeled brace format specification"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("spec,expression", [
    (">4", '"Ada"'),
    ("*>4", '"Ada"'),
    ("+>4", '"Ada"'),
    ("08d", "17"),
    ("#x", "17"),
    (".2f", "1.25"),
    (".{precision}f", "1.25"),
])
def test_admitted_alignment_numeric_and_nested_precision_formats_remain_clean(tmp_path, mode, spec, expression):
    pattern = "{x:" + spec + "}"
    source = f'def render():\n    return gettext({pattern!r}).format(x={expression}, precision=2)\n'
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    assert isinstance(_native(source, po), str)
    assert finding["status"] == "clean"


def _character_source(pattern, expression, *, parameter=False):
    signature = "value: int" if parameter else ""
    if pattern == "%c":
        operation = f'gettext({pattern!r}) % {expression}'
    elif pattern == "%(x)c":
        operation = f'gettext({pattern!r}) % {{"x": {expression}}}'
    elif pattern == "{0:c}":
        operation = f'gettext({pattern!r}).format({expression})'
    else:
        operation = f'gettext({pattern!r}).format(x={expression})'
    return f'def render({signature}):\n    return {operation}\n'


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("pattern", ["%c", "%(x)c", "{x:c}", "{0:c}"])
@pytest.mark.parametrize("value", [-1, 0x110000])
def test_out_of_range_character_literal_is_unknown_not_clean(tmp_path, mode, pattern, value):
    source = _character_source(pattern, repr(value))
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    with pytest.raises(OverflowError):
        _native(source, po)
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("pattern", ["%c", "%(x)c", "{x:c}", "{0:c}"])
@pytest.mark.parametrize("value", [0, 65, 0x10FFFF])
def test_proven_character_literal_range_remains_clean(tmp_path, mode, pattern, value):
    source = _character_source(pattern, repr(value))
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    assert _native(source, po) == chr(value)
    assert finding["status"] == "clean"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("pattern", ["%c", "%(x)c", "{x:c}", "{0:c}"])
def test_unresolved_integer_character_range_remains_unknown(tmp_path, mode, pattern):
    source = _character_source(pattern, "value", parameter=True)
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    assert _native(source, po, 65) == "A"
    with pytest.raises(OverflowError):
        _native(source, po, -1)
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("precision", ["-1", "True", "1.25", '"bad"'])
def test_invalid_nested_precision_is_unknown_not_clean(tmp_path, mode, precision):
    pattern = "{x:.{precision}f}"
    source = f'def render():\n    return gettext({pattern!r}).format(x=1.25, precision={precision})\n'
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    with pytest.raises(ValueError):
        _native(source, po)
    assert finding["status"] == "unknown"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("precision", [0, 2, 8])
def test_bounded_nonnegative_literal_precision_remains_clean(tmp_path, mode, precision):
    pattern = "{x:.{precision}f}"
    source = f'def render():\n    return gettext({pattern!r}).format(x=1.25, precision={precision})\n'
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    assert _native(source, po) == format(1.25, f'.{precision}f')
    assert finding["status"] == "clean"


@pytest.mark.parametrize("mode", ["direct", "flow"])
def test_unresolved_precision_does_not_invent_valid_digits(tmp_path, mode):
    pattern = "{x:.{precision}f}"
    source = f'def render(value: int):\n    return gettext({pattern!r}).format(x=1.25, precision=value)\n'
    po, finding = _fixture(tmp_path, source, pattern, mode=mode)
    assert _native(source, po, 2) == "1.25"
    with pytest.raises(ValueError):
        _native(source, po, -1)
    assert finding["status"] == "unknown"
