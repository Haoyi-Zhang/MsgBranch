"""Bounded scaling measurements for the project-level scanner.

The benchmark generates local source/catalog fixtures.  It reports wall time,
peak Python allocation and cache behavior; it is not an industrial throughput
claim and includes PO parsing/MO compilation in every observation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import platform
import statistics
import tempfile
import time
import tracemalloc

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
import babel

if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.project import audit_project

ROOT = Path(__file__).resolve().parents[1]
SIZES = (1, 25, 100, 400)
REPEATS = 3


def fixture(folder: Path, calls: int, *, repeated: bool) -> tuple[Path, Path]:
    source = folder / "app.py"
    lines = []
    for index in range(calls):
        key = 0 if repeated else index
        lines.append(
            f'r{index} = ngettext("%(n)d item {key}", "%(n)d items {key}", n) % {{"n": n}}'
        )
    source.write_text("def render(n):\n    " + "\n    ".join(lines) + "\n    return r0\n", encoding="utf-8")
    catalog = Catalog(locale="pl", creation_date=datetime(2026, 10, 4, tzinfo=timezone.utc))
    keys = (0,) if repeated else range(calls)
    for key in keys:
        catalog.add(
            (f"%(n)d item {key}", f"%(n)d items {key}"),
            (f"%(n)d rzecz {key}", f"%(n)d rzeczy {key}", f"%(n)d rzeczy {key}"),
            flags={"python-format"},
        )
    out = BytesIO()
    write_po(out, catalog, omit_header=False)
    po = folder / "messages.po"
    po.write_bytes(out.getvalue())
    return source, po


def observation(source: Path, catalog: Path) -> dict:
    tracemalloc.start()
    start = time.perf_counter_ns()
    report = audit_project(source, [catalog], max_count=200)
    wall_ms = (time.perf_counter_ns() - start) / 1e6
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    summary = report["summary"]
    return {
        "wall_ms": wall_ms,
        "peak_kib": peak / 1024,
        "calls": summary["calls"],
        "findings": summary["findings"],
        "selected_patterns": summary["selected_patterns"],
        "unique_runtime_lookup_sets": summary["unique_runtime_lookup_sets"],
        "runtime_lookup_cache_hits": summary["runtime_lookup_cache_hits"],
        "errors": summary["errors"],
        "unknown": summary["unknown"],
    }


def evaluate(*, sizes: tuple[int, ...] = SIZES, repeats: int = REPEATS) -> dict:
    records = []
    with tempfile.TemporaryDirectory(prefix="msgbranch-scaling-") as tmp:
        root = Path(tmp)
        for repeated in (True, False):
            for size in sizes:
                folder = root / ("repeated" if repeated else "unique") / str(size)
                folder.mkdir(parents=True)
                source, catalog = fixture(folder, size, repeated=repeated)
                raw = [observation(source, catalog) for _ in range(repeats)]
                records.append({
                    "shape": "repeated-message" if repeated else "unique-message",
                    "calls": size,
                    "repeats": repeats,
                    "median_wall_ms": statistics.median(row["wall_ms"] for row in raw),
                    "median_peak_kib": statistics.median(row["peak_kib"] for row in raw),
                    "runtime_lookup_sets": raw[-1]["unique_runtime_lookup_sets"],
                    "cache_hits": raw[-1]["runtime_lookup_cache_hits"],
                    "selected_patterns": raw[-1]["selected_patterns"],
                    "errors": raw[-1]["errors"],
                    "unknown": raw[-1]["unknown"],
                    "raw": raw,
                })
    return {
        "python": platform.python_version(),
        "babel": babel.__version__,
        "max_count": 200,
        "records": records,
        "scope": (
            "generated local Python/PO fixtures; includes parsing, Babel MO compilation, AST scan, runtime selection and qualification; "
            "wall time is descriptive for this machine only"
        ),
    }


def main() -> None:
    result = evaluate()
    (ROOT / "results/project-scaling.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{k: row[k] for k in ("shape", "calls", "median_wall_ms", "median_peak_kib", "runtime_lookup_sets", "cache_hits")} for row in result["records"]], indent=2))


if __name__ == "__main__":
    main()
