"""Small same-input catalog/caller comparison; default is a nonexecuting plan.

Native --execute requires an explicit GNU gettext-tools msgfmt executable.
Catalog diagnostics are not scored as caller failures. This is8 authored
controls, not full-app recall, a timing campaign, or a rerun of228catalogs.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
from io import BytesIO
import gettext
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from msgbranch.project import audit_project
from msgbranch.runtime import CatalogRuntime


def controls():
    return [
        dict(id="named-reorder", source="%(name)s has %(n)d items",
             target="%(n)d items for %(name)s", dialect="percent",
             values={"name": "Ada", "n": 2}, expected_native="PASS"),
        dict(id="missing-caller-key", source="%(n)d items", target="%(n)d items",
             dialect="percent", values={}, expected_native="KeyError"),
        dict(id="wrong-caller-type", source="%(n)d items", target="%(n)d items",
             dialect="percent", values={"n": "two"}, expected_native="TypeError"),
        dict(id="catalog-field-mismatch", source="%(n)d items", target="%(owner)s items",
             dialect="percent", values={"n": 2}, expected_native="KeyError",
             expected_compiler_rejection=True),
        dict(id="brace-precision", source="{x:.{precision}f}", target="{x:.{precision}f}",
             dialect="brace", values={"x": 1.25, "precision": 2}, expected_native="PASS"),
        dict(id="bad-caller-precision", source="{x:.{precision}f}", target="{x:.{precision}f}",
             dialect="brace", values={"x": 1.25, "precision": "bad"}, expected_native="ValueError"),
        dict(id="branch-specific-omission", source="one item", plural="%(n)d items",
             target=["un article", "%(n)d articles"], count=1, dialect="percent",
             values={}, expected_native="PASS"),
        dict(id="literal-percent", source="rate: 100%%", target="rate: 100%%",
             dialect="percent", values={}, expected_native="PASS"),
    ]


def po_bytes(case):
    quote = lambda text: json.dumps(text, ensure_ascii=False)
    header = ("Content-Type: text/plain; charset=UTF-8\nLanguage: en\n"
              "Plural-Forms: nplurals=2; plural=(n != 1);\n")
    lines = ['msgid ""', 'msgstr ' + quote(header), "",
             "#, python-brace-format" if case["dialect"] == "brace" else "#, python-format",
             "msgid " + quote(case["source"])]
    if "plural" in case:
        lines += ["msgid_plural " + quote(case["plural"])]
        lines += ["msgstr[" + str(i) + "] " + quote(text) for i, text in enumerate(case["target"])]
    else:
        lines += ["msgstr " + quote(case["target"])]
    return ("\n".join(lines) + "\n").encode("utf-8")


def caller_source(case):
    if "plural" in case:
        lookup = "ngettext(" + repr(case["source"]) + ", " + repr(case["plural"]) + ", " + str(case["count"]) + ")"
    else:
        lookup = "gettext(" + repr(case["source"]) + ")"
    operation = lookup + (" % " + repr(case["values"]) if case["dialect"] == "percent"
                          else ".format(**" + repr(case["values"]) + ")")
    # Use literal keyword suppliers, not ** expansion outside the analyzer grammar.
    if case["dialect"] == "brace":
        operation = lookup + ".format(" + ", ".join(k+"="+repr(v) for k, v in case["values"].items()) + ")"
    return "def render():\n    return " + operation + "\n"


def native_outcome(case, translation):
    if "plural" in case:
        pattern = translation.ngettext(case["source"], case["plural"], case["count"])
    else:
        pattern = translation.gettext(case["source"])
    try:
        output = pattern % case["values"] if case["dialect"] == "percent" else pattern.format(**case["values"])
        return {"status": "PASS", "output": output, "pattern": pattern}
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        return {"status": type(exc).__name__, "message": str(exc), "pattern": pattern}


def execute(executable, output_dir):
    executable, output_dir = Path(executable).resolve(), Path(output_dir).resolve()
    version = subprocess.run([str(executable), "--version"], text=True, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=15)
    help_result = subprocess.run([str(executable), "--help"], text=True, capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=15)
    if version.returncode or "GNU gettext" not in version.stdout or "--check-format" not in help_result.stdout:
        raise ValueError("An available GNU gettext-tools msgfmt with --check-format is required")
    output_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in controls():
        folder = output_dir / case["id"]
        folder.mkdir()
        po, app, mo = folder/"messages.po", folder/"owned.py", folder/"messages.mo"
        po.write_bytes(po_bytes(case))
        app.write_text(caller_source(case), encoding="utf-8")
        argv = [str(executable), "--check-format", "-o", str(mo), str(po)]
        completed = subprocess.run(argv, text=True, capture_output=True, encoding="utf-8",
                                   errors="replace", timeout=30)
        babel_runtime = CatalogRuntime(po)
        reference = native_outcome(case, babel_runtime.translator)
        report = audit_project(app, [po], max_count=2, analysis_mode="flow")
        row = {"case": case, "po_sha256": sha256(po.read_bytes()).hexdigest(),
               "caller_source": caller_source(case),
               "caller_sha256": sha256(app.read_bytes()).hexdigest(),
               "compiler_argv": argv, "compiler_returncode": completed.returncode,
               "compiler_stdout": completed.stdout, "compiler_stderr": completed.stderr,
               "babel_catalog_diagnostics": babel_runtime.checks,
               "babel_native_outcome": reference,
               "msgbranch_finding": report["findings"][0],
               "compiler_acceptance_matches_control": ((completed.returncode != 0)
                   if case.get("expected_compiler_rejection") else (completed.returncode == 0 and mo.exists())),
               "reference_matches_declared_native": reference["status"] == case["expected_native"]}
        if completed.returncode == 0 and mo.exists():
            native = native_outcome(case, gettext.GNUTranslations(BytesIO(mo.read_bytes())))
            row.update(gnu_native_outcome=native,
                       functional_agreement=(native["status"], native.get("output"), native["pattern"])
                       == (reference["status"], reference.get("output"), reference["pattern"]))
        else:
            row.update(gnu_native_outcome=None, functional_agreement=None)
        rows.append(row)
        (output_dir/"progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    result = {"status": "executed", "tool": str(executable),
              "tool_sha256": sha256(executable.read_bytes()).hexdigest(),
              "tool_version": version.stdout, "python": sys.version, "rows": rows,
              "summary": {"controls": len(rows),
                          "compiler_accepted": sum(r["compiler_returncode"] == 0 for r in rows),
                          "native_comparisons": sum(r["gnu_native_outcome"] is not None for r in rows),
                          "native_disagreements": sum(r["functional_agreement"] is False for r in rows),
                          "compiler_control_mismatches": sum(not r["compiler_acceptance_matches_control"] for r in rows),
                          "reference_expectation_mismatches": sum(not r["reference_matches_declared_native"] for r in rows)},
              "scope": "Same PO bytes, flags, caller values, fixed selected counts and exception-free obligation per control. Catalog checking and caller qualification are distinct layers, not interchangeable miss counts. No byte-equivalence, real-defect yield, performance or production claims."}
    (output_dir/"report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--msgfmt", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "unexecuted-plan", "controls": controls(),
                          "native_compiler_run": False}, indent=2))
        return 0
    if args.msgfmt is None or args.output_dir is None:
        parser.error("--execute requires --msgfmt and a fresh --output-dir")
    result = execute(args.msgfmt, args.output_dir)
    print(json.dumps(result["summary"], indent=2))
    return 1 if (result["summary"]["native_disagreements"]
                 or result["summary"]["compiler_control_mismatches"]
                 or result["summary"]["reference_expectation_mismatches"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
