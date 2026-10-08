#!/usr/bin/env python3
"""Check that the manuscript bibliography, citations, and reference ledgers agree."""
from __future__ import annotations
import csv, json, re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent
BIB = WORK / "paper" / "references.bib"
TEX = WORK / "paper" / "main.tex"
JSON_LEDGER = ROOT / "docs" / "references.json"
CSV_LEDGER = ROOT / "docs" / "references.csv"
OUT = ROOT / "results" / "reference-audit.json"

manuscript_present = BIB.is_file() and TEX.is_file()
if manuscript_present:
    bib_text = BIB.read_text(encoding="utf-8")
    tex_text = TEX.read_text(encoding="utf-8")
    bib_keys = re.findall(r"^@\w+\{([^,]+),", bib_text, flags=re.MULTILINE)
    cited: list[str] = []
    for command in ("cite", "bstctlcite"):
        for group in re.findall(rf"\\{command}\{{([^}}]+)\}}", tex_text):
            cited.extend(key.strip() for key in group.split(",") if key.strip())
else:
    # The standalone repository intentionally omits the manuscript. Validate
    # the ledger internally; the complete bundle performs the full TeX/BibTeX audit.
    bib_keys = []
    cited = []
json_rows = json.loads(JSON_LEDGER.read_text(encoding="utf-8"))
with CSV_LEDGER.open(encoding="utf-8", newline="") as handle:
    csv_rows = list(csv.DictReader(handle))
json_keys = [row["key"] for row in json_rows]
csv_keys = [row["key"] for row in csv_rows]
article_keys = [key for key in bib_keys if key != "IEEEcontrol"] if manuscript_present else json_keys.copy()

def duplicates(values: list[str]) -> list[str]:
    return sorted(key for key, count in Counter(values).items() if count > 1)

def duplicate_field(field: str) -> list[str]:
    values = [str(row.get(field, "")).strip().lower() for row in json_rows]
    return duplicates([value for value in values if value])

receipt = {
    "manuscript_present": manuscript_present,
    "scope": "full manuscript/BibTeX/ledger audit" if manuscript_present else "standalone ledger audit; manuscript intentionally absent",
    "bibliography_entries_total": len(bib_keys) if manuscript_present else None,
    "bibliographic_sources": len(article_keys),
    "unique_cited_keys": len(set(cited) - {"IEEEcontrol"}) if manuscript_present else None,
    "missing_bibliography_keys": sorted(set(cited) - set(bib_keys)) if manuscript_present else [],
    "uncited_bibliography_keys": sorted(set(bib_keys) - set(cited)) if manuscript_present else [],
    "duplicate_bibliography_keys": duplicates(bib_keys),
    "json_records": len(json_rows),
    "csv_records": len(csv_rows),
    "json_missing_from_bibliography": sorted(set(json_keys) - set(article_keys)),
    "bibliography_missing_from_json": sorted(set(article_keys) - set(json_keys)),
    "csv_json_key_difference": sorted(set(csv_keys) ^ set(json_keys)),
    "duplicate_json_keys": duplicates(json_keys),
    "duplicate_dois": duplicate_field("doi"),
    "duplicate_canonical_urls": duplicate_field("canonical_url"),
}
errors = [key for key, value in receipt.items() if isinstance(value, list) and value]
if receipt["json_records"] != receipt["csv_records"] or receipt["json_records"] != receipt["bibliographic_sources"]:
    errors.append("record_count_mismatch")
receipt["status"] = "pass" if not errors else "fail"
receipt["error_fields"] = errors
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))
raise SystemExit(0 if receipt["status"] == "pass" else 1)
