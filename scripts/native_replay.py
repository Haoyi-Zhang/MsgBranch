"""Replay every retained generated input with direct native gettext.

Unlike the original generator, this delivery checker does not re-interpret the
boundary at every input. It independently compiles each trusted fixture once,
compiles its PO through Babel, compares all native outcomes with retained raw
records, and separately regenerates/replays every selected planner witness.
It does not replace the full generator's exhaustive signature experiment.
"""
from pathlib import Path
from io import BytesIO
import gettext
import gzip
import json
import platform
from babel.messages.pofile import read_po
from babel.messages.mofile import write_mo
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.partition import plan_partition
from msgbranch.program import Program
from msgbranch.runtime import CatalogRuntime

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'

def require(condition, message):
    if not condition:
        raise ValueError(message)

def replay(study):
    families = json.loads((RESULTS / (study + '.json')).read_text())
    by_id = {row['id']: row for row in families}
    native = {}
    for case in families:
        path = (ROOT / case['source']).resolve()
        require(path.is_relative_to((ROOT / 'data' / study).resolve()), 'Untrusted fixture path')
        with (ROOT / case['catalog']).open('rb') as f:
            catalog = read_po(f, locale=case['locale'])
        data = BytesIO()
        write_mo(data, catalog)
        translator = gettext.GNUTranslations(BytesIO(data.getvalue()))
        namespace = {'gettext': translator.gettext, '_': translator.gettext, 'ngettext': translator.ngettext}
        exec(compile(path.read_text(), '<trusted-native-replay>', 'exec'), namespace)
        native[case['id']] = namespace['message']
    comparisons = 0
    with gzip.open(RESULTS / (study + '-runs.jsonl.gz'), 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            require(row['case'] in by_id, 'Unknown recorded family')
            try:
                outcome = ('ok', native[row['case']](row['n']), None)
            except (KeyError, TypeError, ValueError, IndexError, OverflowError) as error:
                outcome = ('error', None, f'{type(error).__name__}: {error}')
            expected = (row['status'], row['output'], row['error'])
            require(outcome == expected, f"Native replay mismatch: {row['case']} n={row['n']}")
            comparisons += 1
    require(comparisons == sum(x['domain_size'] for x in families), 'Incomplete native replay')
    selections = json.loads((RESULTS / (study + '-selected.json')).read_text())
    replayed = 0
    for record in selections:
        case = by_id[record['case']]
        p = Program((ROOT / case['source']).read_text())
        rt = CatalogRuntime(ROOT / case['catalog'])
        plan = plan_partition(p, rt, high=case['domain_size']-1)
        canonical = json.loads(json.dumps(plan.to_dict()))
        require(canonical == record['plan'], 'Planner receipt changed: ' + case['id'])
        actual = [p.run(rt, count).to_dict() for count in plan.representatives]
        require(actual == record['selected'], 'Selected native witnesses changed: ' + case['id'])
        replayed += len(actual)
    return {'families': len(families), 'native_comparisons': comparisons,
            'plan_receipts_regenerated': len(selections), 'selected_witnesses_replayed': replayed,
            'disagreements': 0, 'status': 'pass'}

def main():
    report = {'python': platform.python_version(), 'status': 'pass',
              'studies': {s: replay(s) for s in ('validation', 'confirmation')},
              'scope': 'Direct native replay of all retained generated outcomes; fresh planner and selected-witness replay. Not fresh exhaustive interpreter/signature generation.'}
    (RESULTS / 'native-replay.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
