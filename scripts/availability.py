"""Record capabilities; unavailable baselines are not zero detections."""
from pathlib import Path
import importlib.util
import importlib.metadata
import json
import platform
import shutil
ROOT = Path(__file__).resolve().parents[1]

def run():
    executable = shutil.which("msgfmt")
    babel_result = json.loads((ROOT / "results/babel-cli.json").read_text(encoding="utf-8"))
    babel_summary = babel_result["summary"]
    data = {
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {n: importlib.metadata.version(n) for n in ["Babel", "attrs", "pytz", "Jinja2", "pytest"]},
        "gnu_msgfmt": {
            "status": "available-not-measured" if executable else "unavailable",
            "path": executable,
            "correct_replay_command": "msgfmt --check --check-format -o OUTPUT.mo messages.po",
            "format_configuration": "PO python-format or python-brace-format flags; not a --language option",
        },
        "babel_cli": {
            "status": "executed",
            "command": "pybabel compile -i INPUT.po -o OUTPUT.mo",
            "result": "results/babel-cli.json",
            "catalogs": babel_summary["catalogs"],
            "successful_catalogs": babel_summary["cli_success"],
            "diagnosed_catalog_errors": babel_summary["cli_failures"],
            "negative_controls": len(babel_result["negative_controls"]),
            "note": "All retained ordinary catalogs plus separate negative controls; common temporary inputs preserve message flags and clear only the template-header fuzzy marker. This is Babel CLI, not GNU msgfmt",
        },
        "msgbranch_project_auditor": {
            "status": "executed",
            "result": "results/project-audit.json",
            "note": "non-executing Python AST scan with runtime-selected catalog witnesses; dynamic and indirect suppliers remain unknown",
        },
        "weblate_application": {
            "status": "not-executed", "package_found": importlib.util.find_spec("weblate") is not None,
            "note": "No full Weblate deployment, ORM, registration or all-check result is claimed",
        },
        "weblate_format_component": {
            "status": "executed-source-excerpts", "version": "weblate-5.13",
            "receipt": "vendor/weblate-format-core/PROVENANCE.json",
            "checks": ["PythonFormatCheck", "PythonBraceFormatCheck"],
            "settings": "PO flags, default and strict-format; explicit unit shim and plural examples",
            "result": "results/weblate-core-summary.json",
        },
        "localhero_cli": {
            "status": "not-executed-complete-cli",
            "note": "No file discovery, project configuration, command integration or service path is claimed",
        },
        "localhero_placeholder_component": {
            "status": "compiled-and-executed-source-component",
            "commit": "af81321af193458f5869befec4481b8507c2d78d",
            "receipt": "vendor/localhero/PROVENANCE.json",
            "result": "results/localhero-core-summary.json",
        },
        "fluent": {"status": "executed-vendored-source", "commit": "e95b07ea07966dec064d09398a265222742bcfa2"},
        "native_suites": {
            "sphinx": "extracted supplying boundary and repair assertions; not full suite",
            "jupyter": "source slice and optional installed-method comparisons; not full suite",
            "openhangar": "native Jinja2 boundary reconstruction; no Flask-Babel app, routes or database",
            "xrpldashboard": "exact changed Jinja expression with Flask-Babel-compatible behavioral slice; no full route or app",
            "azm_crm": "documented missing-MO build boundary replay with one minimal catalog message; no full Django app or suite",
            "bedrock": "seven retained upstream expected outputs; no Django app or full suite",
        },
        "acquisition_limit": "The recorded environment could not download/install GNU msgfmt, full Weblate, or a complete LocalHero CLI environment. The installed Babel CLI was executed separately; source-excerpt acquisition used public project source reads.",
    }
    (ROOT / "results/availability.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    run()
