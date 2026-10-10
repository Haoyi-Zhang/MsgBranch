"""Bounded localization fixtures; input programs are parsed, never imported."""
from io import BytesIO

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
import pytest

from msgbranch.project import audit_project


def analyze(tmp_path, source, pattern, *, plural=False, mode="flow"):
    source_path = tmp_path / "app.py"
    source_path.write_text(source, encoding="utf-8")
    catalog = Catalog(locale="en")
    catalog.add((pattern, pattern) if plural else pattern,
                (pattern, pattern) if plural else pattern)
    data = BytesIO()
    write_po(data, catalog)
    catalog_path = tmp_path / "messages.po"
    catalog_path.write_bytes(data.getvalue())
    return audit_project(source_path, [catalog_path], max_count=2, analysis_mode=mode)


@pytest.mark.parametrize("expression,status", [("'Ada'", "error"), ("3", "clean")])
def test_fixed_plural_selector_preserves_supplier_type(tmp_path, expression, status):
    source = ('def render():\n'
              '    msg = ngettext("{x:d}", "{x:d}", 1)\n'
              f'    return msg.format(x={expression})\n')
    report = analyze(tmp_path, source, "{x:d}", plural=True)
    assert report["findings"][0]["status"] == status


@pytest.mark.parametrize("statement", [
    'for item in []:\n        pass\n    else:\n        args = {}',
    'while False:\n        pass\n    else:\n        args = {}',
    'for item in []:\n        pass\n    else:\n        del args["owner"]',
    'for item in []:\n        return "skip"\n    else:\n        args = {}',
])
def test_loop_else_effects_cannot_be_certified_from_preloop_state(tmp_path, statement):
    source = ('def render():\n    msg = gettext("%(owner)s")\n'
              '    args = {"owner": "Ada"}\n    ' + statement + '\n'
              '    return msg % args\n')
    report = analyze(tmp_path, source, "%(owner)s")
    assert report["summary"]["clean"] == report["summary"]["errors"] == 0
    assert report["summary"]["unknown"] == 1


@pytest.mark.parametrize("assignment", ["n = n + 1", "n += 1", "n = 2"])
def test_rebound_selector_is_not_substituted_by_old_witness(tmp_path, assignment):
    source = ('def render(n: int):\n'
              '    msg = ngettext("%(owner)s", "%(owner)s", n)\n'
              f'    {assignment}\n'
              '    args = {"owner": "Ada"} if n == 1 else {}\n'
              '    return msg % args\n')
    report = analyze(tmp_path, source, "%(owner)s", plural=True)
    assert report["summary"]["clean"] == 0
    assert report["findings"][0]["status"] in {"unknown", "error"}
    relevant = [w for w in report["findings"][0]["witnesses"]
                if any(low is not None and low <= 1 <= high for low, high in w["covered_count_ranges"])]
    assert relevant and all(w["qualification"]["status"] != "clean" for w in relevant)


def test_loop_target_invalidation_preserves_uncertain_lookup_provenance(tmp_path):
    source = ('def render():\n    msg = gettext("ready")\n'
              '    for msg in []:\n        pass\n'
              '    return msg % (1,)\n')
    report = analyze(tmp_path, source, "ready")
    assert report["summary"]["clean"] == 0
    assert report["findings"][0]["status"] == "unknown"


def test_unchanged_selector_alias_remains_resolvable(tmp_path):
    source = ('def render(n: int):\n'
              '    msg = ngettext("%(owner)s", "%(owner)s", n)\n'
              '    alias = n\n'
              '    args = {"owner": "Ada"} if alias == 1 else {"owner": "Lin"}\n'
              '    return msg % args\n')
    assert analyze(tmp_path, source, "%(owner)s", plural=True)["summary"]["clean"] == 1


def test_second_lookup_does_not_revive_first_selector_symbol(tmp_path):
    source = ('def render(n: int):\n'
              '    msg = ngettext("%(owner)s", "%(owner)s", n)\n'
              '    n = n + 1\n'
              '    other = ngettext("unused", "unused", n)\n'
              '    args = {"owner": "Ada"} if n == 1 else {}\n'
              '    return msg % args\n')
    report = analyze(tmp_path, source, "%(owner)s", plural=True)
    assert report["findings"][0]["status"] == "unknown"


@pytest.mark.parametrize("mode", ["direct", "flow"])
@pytest.mark.parametrize("expression,status", [
    ('{"x": "wrong", "x": 7}', "clean"),
    ('{"x": 7, "x": "wrong"}', "error"),
])
def test_literal_mapping_uses_last_duplicate_value(tmp_path, mode, expression, status):
    source = 'def render():\n    return gettext("%(x)d") % ' + expression + '\n'
    report = analyze(tmp_path, source, "%(x)d", mode=mode)
    assert report["findings"][0]["status"] == status


@pytest.mark.parametrize("expression,status", [
    ("2 ** -1", "error"),
    ("2 ** 3", "clean"),
    ("2 ** exponent", "unknown"),
])
def test_integer_power_respects_exponent_sign(tmp_path, expression, status):
    source = 'def render(exponent: int):\n    return gettext("{x:d}").format(x=' + expression + ')\n'
    report = analyze(tmp_path, source, "{x:d}")
    assert report["findings"][0]["status"] == status


def test_power_native_type_controls():
    assert type(2 ** 3) is int
    assert type(2 ** -1) is float
    assert "{x:d}".format_map({"x": "wrong", "x": 7}) == "7"
    with pytest.raises(ValueError):
        "{x:d}".format(x=2 ** -1)
