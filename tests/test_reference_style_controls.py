"""IEEE style-control records are settings, independently of their keys."""
import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/reference_audit.py'


@pytest.mark.parametrize('article_key', ['paper', 'IEEEcontrol', 'authorDisplay'])
def test_reference_audit_uses_entry_type_not_a_reserved_key(tmp_path, article_key):
    artifact, paper = tmp_path/'artifact', tmp_path/'paper'
    (artifact/'scripts').mkdir(parents=True)
    (artifact/'docs').mkdir()
    paper.mkdir()
    target = artifact/'scripts/reference_audit.py'
    target.write_bytes(SCRIPT.read_bytes())
    (paper/'references.bib').write_text(
        '@article{'+article_key+',\n author={A. Author}, title={Owned test}, year={2026}\n}\n'
        '@IEEEtranBSTCTL{firstStyle,\n CTLuse_url={yes}\n}\n'
        '@IEEEtranBSTCTL{secondStyle,\n CTLdash_repeated_names={no}\n}\n', encoding='utf-8')
    (paper/'main.tex').write_text('\\cite{'+article_key+'}\n\\bstctlcite{firstStyle}\n', encoding='utf-8')
    row = {'key': article_key, 'doi': '', 'canonical_url': ''}
    (artifact/'docs/references.json').write_text(json.dumps([row]), encoding='utf-8')
    with (artifact/'docs/references.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    result = subprocess.run([sys.executable, '-B', str(target)], capture_output=True,
                            text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout+result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['bibliography_entries_total'] == 3
    assert receipt['bibliographic_sources'] == receipt['unique_cited_keys'] == 1
    assert receipt['status'] == 'pass'
