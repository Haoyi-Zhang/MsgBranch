"""Bounded scaling measurements for the project-level scanner.

The benchmark generates local source/catalog fixtures.  It reports wall time,
peak Python allocation and cache behavior; it is not an industrial throughput
claim and includes PO parsing/MO compilation in every observation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import importlib.metadata
import json
import platform
import statistics
import sys
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw),
            "sha256": sha256(raw).hexdigest()}


def source_identity() -> dict:
    for name in ("msgbranch", "msgbranch.project", "msgbranch.runtime"):
        expected = ROOT / "src" / Path(*name.split("."))
        expected = expected / "__init__.py" if name == "msgbranch" else expected.with_suffix(".py")
        if Path(sys.modules[name].__file__).resolve() != expected.resolve():
            raise ValueError("scaling imported an implementation outside this source checkout")
    paths = ("src/msgbranch/__init__.py", "src/msgbranch/project.py", "src/msgbranch/runtime.py",
             "scripts/project_scaling.py", "scripts/_repo_bootstrap.py", "pyproject.toml")
    return {name: file_identity(ROOT / name) for name in paths}


def environment() -> dict:
    cpu, cpu_source = platform.processor(), "platform.processor"
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        cpu_source = "Windows ProcessorNameString registry value"
    return {"os": platform.platform(), "system": platform.system(),
            "release": platform.release(), "version": platform.version(),
            "machine": platform.machine(), "cpu_model": cpu, "cpu_source": cpu_source,
            "python": platform.python_version(), "python_full": sys.version,
            "python_implementation": platform.python_implementation(),
            "packages": {name: importlib.metadata.version(name)
                         for name in ("Babel", "attrs", "pytz", "Jinja2")}}


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
    if tracemalloc.is_tracing():
        raise RuntimeError("scaling requires a fresh tracemalloc session per observation")
    started_at = utc_now()
    tracemalloc.start()
    try:
        start = time.perf_counter_ns()
        report = audit_project(source, [catalog], max_count=200)
        wall_ms = (time.perf_counter_ns() - start) / 1e6
        _, peak = tracemalloc.get_traced_memory()
    finally:
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
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
    }


def evaluate(*, sizes: tuple[int, ...] = SIZES, repeats: int = REPEATS,
             fixture_root: Path | None = None, budget_seconds: float = 900,
             progress: bool = False) -> dict:
    started_at = utc_now()
    campaign_start = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = fixture_root or ROOT / "evidence/project-scaling" / run_id / "inputs"
    root.mkdir(parents=True, exist_ok=False)
    bound_source, measured_environment = source_identity(), environment()
    records = []
    for repeated in (True, False):
        for size in sizes:
            folder = root / ("repeated" if repeated else "unique") / str(size)
            folder.mkdir(parents=True)
            source, catalog = fixture(folder, size, repeated=repeated)
            inputs = {"source": file_identity(source), "catalog": file_identity(catalog)}
            raw = []
            for repeat in range(repeats):
                if time.monotonic() - campaign_start >= budget_seconds:
                    raise TimeoutError("project-scaling campaign exceeded its time budget")
                row = observation(source, catalog)
                row["repeat"] = repeat
                if row["calls"] != size or row["findings"] != size or row["errors"] or row["unknown"]:
                    raise ValueError("scaling fixture did not preserve its declared clean call boundaries")
                raw.append(row)
                if progress:
                    print(f"scaling {len(records) * repeats + repeat + 1}/{2 * len(sizes) * repeats}: "
                          f"{'repeated' if repeated else 'unique'} {size} calls, "
                          f"repeat {repeat + 1}, {row['wall_ms']:.3f} ms", file=sys.stderr, flush=True)
            if inputs != {"source": file_identity(source), "catalog": file_identity(catalog)}:
                raise ValueError("scaling input bytes changed during measurement")
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
                "fixture_identity": inputs,
            })
    if source_identity() != bound_source:
        raise ValueError("scaling implementation changed during measurement")
    return {
        "measurement_record_version": 2,
        "run_id": run_id,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "campaign_elapsed_seconds": time.monotonic() - campaign_start,
        "budget_seconds": budget_seconds,
        "environment": measured_environment,
        "source_identity": bound_source,
        "design": {"shapes": ["repeated-message", "unique-message"], "calls": list(sizes),
                   "repeats": repeats, "observations": sum(len(row["raw"]) for row in records),
                   "order": "repeated then unique; ascending calls; three consecutive repeats",
                   "warmup": "none; the first observation is retained"},
        "measurement": {
            "wall_time": "perf_counter_ns immediately around audit_project; milliseconds",
            "included": "source parsing, Babel PO-to-MO compilation, AST scan, runtime selection and qualification",
            "excluded": "fixture generation, hashing, environment/UTC capture and result serialization",
            "peak_allocation": "tracemalloc peak over that audit_project call with a fresh trace; KiB=1024 bytes; not process RSS",
            "aggregation": "median of the three raw wall times and separately median of the three raw peak allocations",
        },
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
    result = evaluate(progress=True)
    if len(result["records"]) != 8 or result["design"]["observations"] != 24:
        raise ValueError("default project-scaling result requires all 24 observations")
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    output = ROOT / "results/project-scaling.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)
    compact = json.dumps([{k: row[k] for k in ("shape", "calls", "median_wall_ms", "median_peak_kib",
                                              "runtime_lookup_sets", "cache_hits")}
                          for row in result["records"]], indent=2) + "\n"
    (ROOT / "results/project-scaling-stdout.json").write_text(compact, encoding="utf-8")
    print(compact, end="")


if __name__ == "__main__":
    main()
