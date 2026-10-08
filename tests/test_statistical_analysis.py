from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_statistical_analysis_matches_frozen_counts():
    subprocess.run(["python", "scripts/statistical_analysis.py"], cwd=ROOT, check=True, capture_output=True, text=True)
    report = json.loads((ROOT / "results/statistical-analysis.json").read_text())
    assert report["validation"]["methods"]["product"]["hits"] == 52
    assert report["validation"]["methods"]["ordinary7"]["hits"] == 4
    assert report["confirmation"]["methods"]["product"]["hits"] == 54
    assert report["confirmation"]["methods"]["ordinary7"]["hits"] == 6
    assert report["validation"]["paired_against_product"]["source_only"]["a_only"] == 14
    assert report["confirmation"]["paired_against_product"]["source_only"]["a_only"] == 18
