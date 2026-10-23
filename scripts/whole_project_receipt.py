"""Recount complete-source classifications and bindings without rerunning scans."""
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def identity(row):
    call = row['call']
    return call['path'], call['line'], call['column'], row.get('catalog')


def validate(record, root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / 'data/whole-project/solaar-inputs.json').read_text(encoding='utf-8'))
    if record['input'] != manifest or record['inputs_bound'] != len(manifest['files']) or len(manifest['files']) != 130:
        raise ValueError('Input manifest or population mismatch')
    expected_sources = {p.relative_to(root).as_posix() for p in (root / 'src/msgbranch').glob('*.py')}
    expected_sources |= {'scripts/whole_project_scan.py', 'scripts/_repo_bootstrap.py',
                         'data/whole-project/solaar-inputs.json'}
    if set(record['source_bindings']) != expected_sources:
        raise ValueError('Measured source coverage mismatch')
    for relative, digest in record['source_bindings'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Measured source identity mismatch: ' + relative)
    configuration = record['configuration']
    if configuration != {'modes': ['direct', 'flow'], 'count_domain': [0, 200],
                         'require_catalog': False, 'source_modules_executed': False,
                         'singular_callees': ['gettext', '_'], 'plural_callees': ['ngettext'],
                         'contextual_callees': ['pgettext', 'npgettext']}:
        raise ValueError('Changed whole-source configuration')
    summaries = {}
    keyed = {}
    for mode in ('direct', 'flow'):
        report = record['reports'][mode]
        rows, summary = report['findings'], report['summary']
        if not rows or summary['analysis_mode'] != mode or summary['python_files'] != 128:
            raise ValueError('Missing complete scan population')
        keyed[mode] = {identity(row): row for row in rows}
        if len(keyed[mode]) != len(rows):
            raise ValueError('Duplicate finding identity')
        counts = Counter(row['status'] for row in rows)
        if set(counts) - {'clean', 'error', 'unknown'}:
            raise ValueError('Invalid classification')
        if summary['calls'] != len(rows) or summary['findings'] != len(rows):
            raise ValueError('Incomplete finding accounting')
        for status, field in [('clean', 'clean'), ('error', 'errors'), ('unknown', 'unknown')]:
            if summary[field] != counts[status]:
                raise ValueError('Classification count mismatch')
        if summary['selected_patterns'] != sum(len(r.get('witnesses', [])) for r in rows):
            raise ValueError('Witness count mismatch')
        if summary['literal_calls'] != sum(r['call']['status'] == 'literal' for r in rows):
            raise ValueError('Literal-call count mismatch')
        execution = report['execution']
        start = datetime.fromisoformat(execution['started_at_utc'])
        end = datetime.fromisoformat(execution['completed_at_utc'])
        if not (start.tzinfo and end.tzinfo and start < end and
                0 < execution['elapsed_seconds'] < execution['wall_budget_seconds'] == 180 and
                execution['upstream_modules_imported_or_executed'] is False):
            raise ValueError('Execution identity or budget mismatch')
        summaries[mode] = dict(summary)
    if set(keyed['direct']) != set(keyed['flow']):
        raise ValueError('The compared call/catalog populations differ')
    transitions = Counter(keyed['direct'][k]['status'] + '_to_' + keyed['flow'][k]['status']
                          for k in keyed['direct'])
    return {'status': 'pass', 'python_files': 128, 'inputs_bound': 130,
            'findings_per_mode': len(keyed['flow']), 'methods': summaries,
            'classification_transitions': dict(sorted(transitions.items())),
            'scope': 'Raw-count and measured-source identity validation, not field-defect adjudication'}


def read_current(root=ROOT):
    root = Path(root)
    record = json.loads(gzip.decompress((root / 'results/whole-project.json.gz').read_bytes()))
    checked = validate(record, root)
    summary = json.loads((root / 'results/whole-project-summary.json').read_text(encoding='utf-8'))
    if (summary['inputs_bound'] != checked['inputs_bound'] or
            summary['source_bindings'] != record['source_bindings'] or
            summary['configuration'] != record['configuration'] or
            summary['classification_transitions'] != checked['classification_transitions'] or
            summary['same_finding_identities'] is not True):
        raise ValueError('Detached summary mismatch')
    for mode in ('direct', 'flow'):
        if summary['methods'][mode]['summary'] != checked['methods'][mode]:
            raise ValueError('Detached method summary mismatch')
    return checked


if __name__ == '__main__':
    print(json.dumps(read_current(), ensure_ascii=False, indent=2))
