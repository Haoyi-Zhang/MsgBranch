from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import csv
import json

ROOT = Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "corpus/public-fix-screen.json").read_text())
ids = [row["case_id"] for row in rows]
if len(ids) != len(set(ids)):
    raise ValueError("duplicate case_id")
for row in rows:
    if not row["url"].startswith("https://github.com/"):
        raise ValueError(f"non-GitHub source in {row['case_id']}")
    if row["replay_status"] in {"replayed", "behavioral-slice-replay"}:
        for field in ("cheap_nonproduct_check_detects", "guard_product_needed"):
            if row[field] is None:
                raise ValueError(f"missing executed classification {row['case_id']}:{field}")

replayed = [row for row in rows if row["replay_status"] in {"replayed", "behavioral-slice-replay"}]
groups = defaultdict(list)
for row in rows:
    groups[row["repair_group"]].append(row["case_id"])
summary = {
    "candidates": len(rows),
    "unique_repair_groups": len(groups),
    "executed_historical_repairs": len(replayed),
    "executed_detected_by_ordinary_1_2": sum(bool(row["ordinary_1_2_detects"]) for row in replayed),
    "executed_detected_by_cheap_nonproduct": sum(bool(row["cheap_nonproduct_check_detects"]) for row in replayed),
    "executed_requiring_guard_product": sum(bool(row["guard_product_needed"]) for row in replayed),
    "dispositions": dict(sorted(Counter(row["disposition"] for row in rows).items())),
    "replay_scope": {row["case_id"]: row["replay_status"] for row in replayed},
    "interpretation": "The screen broadens public maintenance evidence but establishes no incremental real-defect yield over cheap non-product checks. Unreplayed and development-stage leads are not counted as misses or defects."
}
(ROOT / "results/public-fix-screen-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
with (ROOT / "corpus/public-fix-screen.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(json.dumps(summary, indent=2))
