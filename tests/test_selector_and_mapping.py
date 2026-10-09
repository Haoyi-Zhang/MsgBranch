from pathlib import Path

import pytest

from msgbranch.project import audit_project


def catalog(path: Path) -> Path:
    path.write_text(
        'msgid ""\nmsgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Language: en\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("selector,status", [("1", "clean"), ("2", "error"), ("n", "error"), ("n + 1", "unknown"), ("-1", "unknown")])
@pytest.mark.parametrize("mode", ["direct", "flow"])
def test_plural_selector_respects_the_call_domain(tmp_path, selector, status, mode):
    source = tmp_path / "app.py"
    source.write_text(
        f'def message(n):\n    return ngettext("One item", "%(n)d items", {selector}) % {{}}\n',
        encoding="utf-8",
    )
    report = audit_project(source, [catalog(tmp_path / "messages.po")], max_count=4, analysis_mode=mode)
    assert report["findings"][0]["status"] == status
    if selector in {"1", "2"}:
        assert [w["count"] for w in report["findings"][0]["witnesses"]] == [int(selector)]


def test_fixed_and_domain_selectors_do_not_share_lookup_cache(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def message(n):\n'
        '    a = ngettext("One item", "%(n)d items", 1) % {}\n'
        '    b = ngettext("One item", "%(n)d items", n) % {}\n'
        '    return a, b\n',
        encoding="utf-8",
    )
    report = audit_project(source, [catalog(tmp_path / "messages.po")], max_count=4)
    assert [f["status"] for f in report["findings"]] == ["clean", "error"]
    assert report["summary"]["unique_runtime_lookup_sets"] == 2


@pytest.mark.parametrize("directive", ["s", "r", "a"])
@pytest.mark.parametrize("values", [{}, {"x": 1}])
@pytest.mark.parametrize("mode", ["direct", "flow"])
def test_mapping_is_one_object_for_unkeyed_conversion(tmp_path, directive, values, mode):
    pattern = "%" + directive
    assert isinstance(pattern % values, str)
    source = tmp_path / "app.py"
    source.write_text(f'def message():\n    return gettext("{pattern}") % {values!r}\n', encoding="utf-8")
    report = audit_project(source, [catalog(tmp_path / "messages.po")], analysis_mode=mode)
    assert report["findings"][0]["status"] == "clean"


@pytest.mark.parametrize("pattern,status", [("%d", "error"), ("%(n)d", "error"), ("%(x)s %s", "unknown"), ("%s %s", "error")])
def test_mapping_rules_keep_key_type_and_arity_obligations(tmp_path, pattern, status):
    source = tmp_path / "app.py"
    source.write_text(f'def message():\n    return gettext("{pattern}") % {{"x": 1}}\n', encoding="utf-8")
    report = audit_project(source, [catalog(tmp_path / "messages.po")])
    assert report["findings"][0]["status"] == status
