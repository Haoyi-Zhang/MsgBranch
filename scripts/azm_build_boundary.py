"""Replay the runtime-artifact boundary from AZM CRM commit 326d0f9d.

The historical defect was absence of the compiled MO in CI, not an invalid PO.
This local slice therefore compares Python's source fallback with the same PO
compiled through the pinned Babel writer and loaded by GNUTranslations.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import gettext
import json
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.runtime import CatalogRuntime

ROOT = Path(__file__).resolve().parents[1]
MESSAGE = "Ticket queue"
EXPECTED = "قائمة التذاكر"


def replay() -> dict:
    po = ROOT / "data/azm-build/messages.po"
    before_translator = gettext.NullTranslations()
    before = before_translator.gettext(MESSAGE)
    runtime = CatalogRuntime(po)
    after = gettext.GNUTranslations(BytesIO(runtime.mo)).gettext(MESSAGE)
    return {
        "case": "azm-build-326d0f",
        "historical_repair": "326d0f9d0d964eef90ebc33f5303c26a0f24064f",
        "parent": "730e121364558e1e4c971e9f86bd4d620d783fca",
        "before": {"mo_present": False, "output": before, "falls_back_to_source": before == MESSAGE},
        "after": {"mo_present": True, "output": after, "translated": after == EXPECTED, "mo_bytes": len(runtime.mo)},
        "babel_checks": runtime.checks,
        "ordinary_smoke_detects": before != after and after == EXPECTED,
        "guard_product_needed": False,
        "claim": "build-artifact boundary slice; no Django route or full upstream suite executed",
    }


def main() -> None:
    result = replay()
    assert result["before"]["falls_back_to_source"]
    assert result["after"]["translated"]
    assert not result["babel_checks"]
    path = ROOT / "results/azm-build.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
