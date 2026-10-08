from pathlib import Path
import json

from scripts.coverage_report import load_jsonl


def test_jsonl_reader_does_not_treat_unicode_nel_as_a_record_separator(tmp_path: Path):
    path = tmp_path / "records.jsonl"
    rows = [
        {"n": 133, "output": "\u0085 item"},
        {"n": 134, "output": "\u0086 item"},
    ]
    # Write the characters literally to exercise the exact failure mode.
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    assert load_jsonl(path) == rows
