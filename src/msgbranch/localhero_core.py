"""Execute the vendored LocalHero placeholder-mismatch source component.

The wrapper supplies already-flattened PO source/target maps. It does not claim
to execute LocalHero file discovery, project configuration, or its other checks.
"""
from __future__ import annotations
from pathlib import Path
import json
import subprocess
import tempfile
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "localhero"


def flatten_catalog(catalog: Iterable[Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Represent each PO form using LocalHero's numbered gettext-key convention."""
    source: dict[str, str] = {}
    target: dict[str, str] = {}
    serial = 0
    for message in catalog:
        if not message.id:
            continue
        base = f"message_{serial}"
        serial += 1
        ids = list(message.id) if isinstance(message.id, (tuple, list)) else [message.id]
        strings = list(message.string) if isinstance(message.string, (tuple, list)) else [message.string or ""]
        forms = max(len(ids), len(strings))
        for index in range(forms):
            key = base if index == 0 else f"{base}__plural_{index}"
            source[key] = str(ids[min(index, len(ids) - 1)])
            target[key] = str(strings[index] if index < len(strings) and strings[index] is not None else "")
    return source, target


def run_component(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run Node on the compiled, vendored TypeScript component."""
    runner = VENDOR / "run-check.mjs"
    if not runner.exists() or not (VENDOR / "dist" / "check-utils.js").exists():
        raise RuntimeError("LocalHero source component is missing; run tsc -p vendor/localhero/tsconfig.json")
    with tempfile.TemporaryDirectory(prefix="msgbranch-localhero-") as td:
        inp = Path(td) / "input.json"
        out = Path(td) / "output.json"
        inp.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            ["node", str(runner), str(inp), str(out)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"LocalHero component failed ({proc.returncode}): {proc.stderr.strip()}")
        return json.loads(out.read_text(encoding="utf-8"))
