from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_public_fix_screen_accounting():
    subprocess.run(["python", "scripts/public_fix_screen.py"], cwd=ROOT, check=True, capture_output=True, text=True)
    summary = json.loads((ROOT / "results/public-fix-screen-summary.json").read_text())
    assert summary["candidates"] == 20
    assert summary["executed_historical_repairs"] == 4
    assert summary["executed_detected_by_ordinary_1_2"] == 3
    assert summary["executed_detected_by_cheap_nonproduct"] == 4
    assert summary["executed_requiring_guard_product"] == 0
