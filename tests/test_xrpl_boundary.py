from pathlib import Path
import json
import subprocess
import os
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_xrpl_repair_replay():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'vendor/python-fluent')])
    subprocess.run([sys.executable, "scripts/xrpl_boundary.py"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    summary = json.loads((ROOT / "results/xrpldashboard-summary.json").read_text())
    assert summary["before_failures"] == 4
    assert summary["after_failures"] == 0
    assert summary["ordinary_count_one_detects"]
