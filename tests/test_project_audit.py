from pathlib import Path
import json
import subprocess
import sys

from msgbranch.project import audit_project, pattern_requirements, scan_source


def po(path: Path, entries: str, plural: str = "nplurals=2; plural=(n != 1);", language: str = "en") -> Path:
    path.write_text(
        'msgid ""\nmsgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        f'"Language: {language}\\n"\n'
        f'"Plural-Forms: {plural}\\n"\n\n' + entries,
        encoding="utf-8",
    )
    return path


def test_scanner_never_executes_source_and_finds_direct_mapping(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'raise RuntimeError("must never execute")\n'
        'def render(n):\n'
        '    return ngettext("%(x)d item", "%(x)d items", n) % {"x": n}\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-format
msgid "%(x)d item"
msgid_plural "%(x)d items"
msgstr[0] "%(x)d thing"
msgstr[1] "%(x)d things"
''')
    report = audit_project(source, [catalog], max_count=4)
    assert report["summary"]["calls"] == 1
    assert report["summary"]["errors"] == 0
    assert report["summary"]["unknown"] == 0


def test_branch_specific_missing_field_is_an_error(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(n):\n'
        '    return ngettext("%(x)d item", "%(x)d items", n) % {"x": n}\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-format
msgid "%(x)d item"
msgid_plural "%(x)d items"
msgstr[0] "%(x)d thing"
msgstr[1] "%(y)d things"
''')
    report = audit_project(source, [catalog], max_count=4)
    assert report["summary"]["errors"] == 1
    bad = [w for w in report["findings"][0]["witnesses"] if w["qualification"]["status"] == "error"]
    assert bad[0]["qualification"]["missing"] == ["y"]


def test_plural_form_may_omit_placeholder(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(n):\n'
        '    return ngettext("%(count)d item", "%(count)d items", n) % {"count": n}\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "ar.po", '''
#, python-format
msgid "%(count)d item"
msgid_plural "%(count)d items"
msgstr[0] "nothing"
msgstr[1] "one"
msgstr[2] "two"
msgstr[3] "%(count)d few"
msgstr[4] "%(count)d many"
msgstr[5] "%(count)d other"
''', 'nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5;', 'ar')
    report = audit_project(source, [catalog], max_count=101)
    assert report["summary"]["errors"] == 0
    assert report["summary"]["selected_patterns"] == 6


def test_dynamic_supplier_is_unknown_not_clean(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(n, values):\n'
        '    return ngettext("%(x)d item", "%(x)d items", n) % values\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-format
msgid "%(x)d item"
msgid_plural "%(x)d items"
msgstr[0] "%(x)d thing"
msgstr[1] "%(x)d things"
''')
    report = audit_project(source, [catalog], max_count=2)
    assert report["summary"]["unknown"] == 1
    assert report["summary"]["errors"] == 0


def test_source_fallback_is_checked_and_optional_presence_obligation(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(n):\n'
        '    return ngettext("one", "%(x)d many", n) % {}\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '')
    report = audit_project(source, [catalog], max_count=2)
    assert report["summary"]["errors"] == 1
    strict = audit_project(source, [catalog], max_count=2, require_catalog=True)
    assert strict["summary"]["errors"] == 1
    assert any(w["fallback"] for w in strict["findings"][0]["witnesses"])


def test_call_keywords_are_a_known_newstyle_supplier(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(n):\n'
        '    return ngettext("%(n)d item", "%(n)d items", n, n=n)\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-format
msgid "%(n)d item"
msgid_plural "%(n)d items"
msgstr[0] "%(n)d thing"
msgstr[1] "%(n)d things"
''')
    report = audit_project(source, [catalog], max_count=2)
    assert report["summary"]["errors"] == 0
    assert report["summary"]["unknown"] == 0


def test_dynamic_identifier_and_parse_failure_are_unknown():
    dynamic = scan_source('ngettext(key, "many", n)', "dynamic.py")
    assert dynamic[0].status == "unknown"
    broken = scan_source('def nope(:\n', "broken.py")
    assert broken[0].status == "unknown"


def test_pattern_requirement_parser_covers_named_and_positional():
    assert pattern_requirements("%(name)s: %d").names == ("name",)
    assert pattern_requirements("%(name)s: %d").positional == 1
    assert pattern_requirements("{name} {0}").dialect == "brace"
    assert pattern_requirements("{name} {0}").positional == 1
    assert pattern_requirements("100%% ready").dialect == "percent"


def test_project_cli_writes_machine_readable_report(tmp_path):
    source = tmp_path / "app.py"
    source.write_text('x = gettext("Hello")\n', encoding="utf-8")
    catalog = po(tmp_path / "messages.po", 'msgid "Hello"\nmsgstr "Bonjour"\n')
    output = tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, "-m", "msgbranch.project", str(source), str(catalog), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["clean"] == 1


def test_overloaded_wrapper_uses_arity_to_classify_calls(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(n):\n'
        '    status = __("ok")\n'
        '    msg = __("%(n)d item", "%(n)d items", n)\n'
        '    return msg % {"n": n}\n',
        encoding="utf-8",
    )
    calls = scan_source(source.read_text(), source.name, overloaded_callees=("__",))
    assert [call.kind for call in calls] == ["singular", "plural"]


def test_repeated_message_ids_share_runtime_lookup_witnesses(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'a = gettext("Hello")\n'
        'b = gettext("Hello")\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", 'msgid "Hello"\nmsgstr "Bonjour"\n')
    report = audit_project(source, [catalog])
    assert report["summary"]["calls"] == 2
    assert report["summary"]["unique_runtime_lookup_sets"] == 1
    assert report["summary"]["runtime_lookup_cache_hits"] == 1


def test_flow_recovers_indirect_supplier_and_count_type(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render(items):\n'
        '    count = len(items)\n'
        '    msg = ngettext("%d item", "%d items", count)\n'
        '    return msg % count\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-format
msgid "%d item"
msgid_plural "%d items"
msgstr[0] "%d thing"
msgstr[1] "%d things"
''')
    flow = audit_project(source, [catalog], max_count=3, analysis_mode="flow")
    direct = audit_project(source, [catalog], max_count=3, analysis_mode="direct")
    assert flow["summary"]["clean"] == 1
    assert flow["summary"]["unknown"] == 0
    assert flow["summary"]["flow_recovered_calls"] == 1
    assert direct["summary"]["unknown"] == 1


def test_witness_conditioned_supplier_exposes_count_100_missing_and_type_error(tmp_path):
    missing_source = tmp_path / "missing.py"
    missing_source.write_text(
        'def render(n: int):\n'
        '    msg = ngettext("%(n)d item", "%(n)d items", n)\n'
        '    values = {} if n == 100 else {"n": n}\n'
        '    return msg % values\n',
        encoding="utf-8",
    )
    type_source = tmp_path / "type.py"
    type_source.write_text(
        'def render(n: int):\n'
        '    msg = ngettext("%(n)d item", "%(n)d items", n)\n'
        '    value = str(n) if n == 100 else n\n'
        '    return msg % {"n": value}\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-format
msgid "%(n)d item"
msgid_plural "%(n)d items"
msgstr[0] "%(n)d thing"
msgstr[1] "%(n)d things"
''')
    missing = audit_project(missing_source, [catalog], max_count=100)
    typed = audit_project(type_source, [catalog], max_count=100)
    missing_witnesses = missing["findings"][0]["witnesses"]
    type_witnesses = typed["findings"][0]["witnesses"]
    assert [(w["count"], w["qualification"]["status"]) for w in missing_witnesses] == [
        (0, "clean"),
        (1, "clean"),
        (100, "error"),
    ]
    assert type_witnesses[-1]["count"] == 100
    assert type_witnesses[-1]["qualification"]["type_mismatches"] == [
        {"field": "n", "required": "decimal", "supplied": "str"}
    ]


def test_contextual_gettext_and_npgettext_use_real_runtime_context(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def labels(n: int):\n'
        '    title = pgettext("menu", "Open")\n'
        '    files = npgettext("files", "%(n)d file", "%(n)d files", n) % {"n": n}\n'
        '    return title, files\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
msgctxt "menu"
msgid "Open"
msgstr "Ouvrir"

#, python-format
msgctxt "files"
msgid "%(n)d file"
msgid_plural "%(n)d files"
msgstr[0] "%(n)d fichier"
msgstr[1] "%(n)d fichiers"
''', 'nplurals=2; plural=(n > 1);', 'fr')
    report = audit_project(source, [catalog], max_count=3)
    assert report["summary"]["calls"] == 2
    assert report["summary"]["clean"] == 2
    contexts = {finding["call"]["context"] for finding in report["findings"]}
    assert contexts == {"menu", "files"}
    outputs = {w["pattern"] for finding in report["findings"] for w in finding["witnesses"]}
    assert "Ouvrir" in outputs
    assert "%(n)d fichier" in outputs


def test_nested_brace_spec_recovers_both_fields_and_types(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        'def render():\n'
        '    return gettext("{value:.{precision}f}").format(value=1.25, precision=2)\n',
        encoding="utf-8",
    )
    catalog = po(tmp_path / "messages.po", '''
#, python-brace-format
msgid "{value:.{precision}f}"
msgstr "{value:.{precision}f}"
''')
    report = audit_project(source, [catalog])
    assert report["summary"]["clean"] == 1
    requirements = report["findings"][0]["witnesses"][0]["qualification"]["requirements"]
    assert requirements["names"] == ("precision", "value")


def test_cli_can_emit_reviewable_pytest_guard(tmp_path):
    source = tmp_path / "app.py"
    source.write_text('x = gettext("Hello")\n', encoding="utf-8")
    catalog = po(tmp_path / "messages.po", 'msgid "Hello"\nmsgstr "Bonjour"\n')
    guard = tmp_path / "test_msgbranch_guard.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "msgbranch.project",
            str(source),
            str(catalog),
            "--emit-pytest",
            str(guard),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "test_localized_message_boundaries" in guard.read_text(encoding="utf-8")
