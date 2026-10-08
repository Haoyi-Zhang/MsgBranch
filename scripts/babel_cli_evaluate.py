"""Run the installed Babel CLI as a complete PO-to-MO build baseline.

This is not GNU msgfmt.  It executes ``pybabel compile`` in subprocesses and
records return codes, diagnostics and byte agreement with MsgBranch's in-process
Babel writer on a frozen, bounded catalog set.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import gettext
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
from babel.messages.pofile import read_po, write_po

if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.runtime import CatalogRuntime

ROOT = Path(__file__).resolve().parents[1]


def frozen_catalogs() -> list[Path]:
    # All retained ordinary catalogs, including application slices and both
    # generated studies. Malformed controls are evaluated separately.
    return sorted(p for p in (ROOT / 'data').rglob('*.po')
                  if p.parent != ROOT / 'data/babel-cli')


def compile_one(executable: str, source: Path, output: Path) -> dict:
    cli_input = source
    header_normalized = False
    try:
        with source.open('rb') as stream:
            catalog = read_po(stream)
        # Parse and serialize a common temporary input once. An absent creation
        # date otherwise defaults to the wall clock separately in the two
        # compilers, which can cross a minute boundary during a slow CI run.
        # Retain message flags; clear only the header-fuzzy marker that makes
        # the CLI skip the entire template catalog.
        header_normalized = catalog.fuzzy
        catalog.fuzzy = False
        cli_input = output.with_suffix('.po')
        with cli_input.open('wb') as stream:
            write_po(stream, catalog)
    except (UnicodeError, ValueError, LookupError):
        pass  # malformed inputs are handed unchanged to the actual CLI
    completed = subprocess.run(
        [executable, "compile", "-i", str(cli_input), "-o", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return {
        "source": str(source.relative_to(ROOT)),
        "compiler_input": str(cli_input),
        "compiler_input_sha256": sha256(cli_input.read_bytes()).hexdigest(),
        "template_header_fuzzy_cleared": header_normalized,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_exists": output.exists(),
        "output_bytes": output.stat().st_size if output.exists() else 0,
        "output_sha256": sha256(output.read_bytes()).hexdigest() if output.exists() else None,
    }


def evaluate() -> dict:
    executable = shutil.which("pybabel")
    if not executable:
        return {"status": "unavailable", "reason": "pybabel not found"}
    rows = []
    with tempfile.TemporaryDirectory(prefix="msgbranch-babel-") as tmp:
        tmpdir = Path(tmp)
        for index, source in enumerate(frozen_catalogs()):
            output = tmpdir / f"catalog-{index}.mo"
            row = compile_one(executable, source, output)
            compiler_input = Path(row.pop('compiler_input'))
            try:
                runtime = CatalogRuntime(compiler_input)
                row["in_process_status"] = "ok"
                row["in_process_checks"] = runtime.checks
                row["in_process_sha256"] = sha256(runtime.mo).hexdigest()
                row["byte_equal_to_in_process"] = output.exists() and output.read_bytes() == runtime.mo
                if output.exists():
                    cli_catalog = gettext.GNUTranslations(BytesIO(output.read_bytes()))._catalog
                    in_process_catalog = gettext.GNUTranslations(BytesIO(runtime.mo))._catalog
                    row["functional_equal_to_in_process"] = cli_catalog == in_process_catalog
                else:
                    row["functional_equal_to_in_process"] = False
            except Exception as exc:  # recorded baseline availability, never a silent pass
                row["in_process_status"] = "error"
                row["in_process_error"] = f"{type(exc).__name__}: {exc}"
                row["byte_equal_to_in_process"] = False
            rows.append(row)
        negatives = []
        for name in ("format-mismatch.po", "invalid-encoding.po"):
            source = ROOT / "data/babel-cli" / name
            control = compile_one(executable, source, tmpdir / f"negative-{name}.mo")
            control.pop('compiler_input')
            negatives.append(control)
    successful = [row for row in rows if row["returncode"] == 0 and row["output_exists"]]
    return {
        "status": "executed",
        "tool": executable,
        "catalogs": rows,
        "negative_controls": negatives,
        "summary": {
            "catalogs": len(rows),
            "cli_success": len(successful),
            "cli_failures": len(rows) - len(successful),
            "byte_equal": sum(bool(row.get("byte_equal_to_in_process")) for row in successful),
            "functional_equal": sum(bool(row.get("functional_equal_to_in_process")) for row in successful),
            "all_outputs_equal": sum(bool(row.get('functional_equal_to_in_process')) for row in rows),
            "format_diagnostics_agree": all((row['returncode'] != 0) == bool(row.get('in_process_checks')) for row in rows),
            "format_mismatch_rejected": negatives[0]["returncode"] != 0,
            "invalid_encoding_rejected": negatives[1]["returncode"] != 0,
        },
        "scope": "Babel CLI compilation/checking on common temporary PO inputs with a fixed metadata header and only the header-fuzzy marker cleared; message flags remain unchanged. Not GNU msgfmt, Weblate, LocalHero file discovery, or application execution.",
    }


def main() -> None:
    result = evaluate()
    (ROOT / "results/babel-cli.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result.get("summary", result), ensure_ascii=False, indent=2))
    if result.get("status") != "executed":
        raise SystemExit(2)
    summary = result["summary"]
    if not summary['format_diagnostics_agree'] or summary["all_outputs_equal"] != summary["catalogs"]:
        raise SystemExit(1)
    if not summary["format_mismatch_rejected"] or not summary["invalid_encoding_rejected"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
