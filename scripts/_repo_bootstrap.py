"""Source-checkout import bootstrap shared by executable research scripts."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "vendor" / "python-fluent"):
    value = str(candidate)
    if candidate.exists() and value not in sys.path:
        sys.path.insert(0, value)
