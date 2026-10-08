"""Replay the versioned xrpldashboard ngettext/Jinja boundary repair."""
from __future__ import annotations
from pathlib import Path
import json
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "xrpldashboard"


def flask_babel_compatible_ngettext(singular: str, plural: str, num: int, **variables):
    """Behavioral slice: select, provide ``num``, then percent-interpolate variables."""
    variables.setdefault("num", num)
    selected = singular if num == 1 else plural
    return selected if not variables else selected % variables


def execute(version: str, count: int):
    env = Environment(undefined=StrictUndefined, autoescape=False)
    env.globals["ngettext"] = flask_babel_compatible_ngettext
    template = env.from_string((DATA / f"{version}.jinja").read_text())
    try:
        value = template.render(verified_strict_count=count).strip()
        return {"version": version, "count": count, "status": "ok", "output": value, "error": None}
    except Exception as exc:
        return {"version": version, "count": count, "status": "error", "output": None, "error": type(exc).__name__, "message": str(exc)}


rows = [execute(version, count) for version in ("before", "after") for count in (0, 1, 2, 100)]
summary = {
    "case": "xrpldashboard-e03829d5",
    "native_boundary_executions": len(rows),
    "before_failures": sum(row["version"] == "before" and row["status"] == "error" for row in rows),
    "after_failures": sum(row["version"] == "after" and row["status"] == "error" for row in rows),
    "ordinary_count_one_detects": next(row for row in rows if row["version"] == "before" and row["count"] == 1)["status"] == "error",
    "unique_over_ordinary_count_one": 0,
    "scope": "Exact changed Jinja expression with a Flask-Babel-compatible ngettext behavioral slice; not full Flask route/application execution."
}
(ROOT / "results" / "xrpldashboard-runs.json").write_text(json.dumps(rows, indent=2) + "\n")
(ROOT / "results" / "xrpldashboard-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
