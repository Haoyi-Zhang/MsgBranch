"""Independently recount retained observations and witness/baseline outcomes.

This checker does not import the planner or its interpreter. It verifies result
accounting, not the mathematical correctness of those implementations. A fresh
--full CI run separately recomputes native comparisons.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
import gzip
import json
import math
import statistics

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'results'

def load(name):
    return json.loads((R / name).read_text())

def require(condition, message):
    if not condition:
        raise ValueError(message)

def audit_project_scaling(scaling, *, root=ROOT):
    """Check 24 retained observations and their exact measured/current source scope."""
    root = Path(root).resolve()
    require(scaling.get('measurement_record_version') == 2, 'scaling source-bound receipt required')
    design = scaling['design']
    require(design['shapes'] == ['repeated-message', 'unique-message'] and
            design['calls'] == [1, 25, 100, 400] and design['repeats'] == 3 and
            design['observations'] == 24, 'scaling design must retain all 24 observations')
    require(scaling['max_count'] == 200, 'scaling count domain')
    require(0 < scaling['campaign_elapsed_seconds'] <= scaling['budget_seconds'] <= 900,
            'scaling measurement budget')

    def stamp(value):
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), 'scaling UTC required')
        return parsed

    started, completed = stamp(scaling['started_at_utc']), stamp(scaling['completed_at_utc'])
    require(started < completed and scaling['run_id'], 'scaling run identity')
    env = scaling['environment']
    require(all(env.get(key) for key in ('os', 'cpu_model', 'cpu_source', 'python', 'python_full',
                                        'python_implementation', 'packages')), 'scaling environment identity')
    require(env['python'] == scaling['python'] and env['packages']['Babel'] == scaling['babel'],
            'scaling environment consistency')
    require(all(scaling['measurement'].get(key) for key in
                ('wall_time', 'included', 'excluded', 'peak_allocation', 'aggregation')), 'scaling measurement definition')

    captured_source = 'scripts/provenance/project-scaling-source.py'
    association_path = root / 'scripts/provenance/project-scaling-association.json'
    old_project = 'd041dd2ba16c85325ece4f0e5750a4205aee754bedea5a3e5775569f82c189bc'
    reviewed_project = 'c8593b33784cecdad9a97aa84154e30e29ca637bbdd5d8b0ad320ae5f6e5dc6a'
    retained_receipt = '1e437131087c0682966d5758b2e416d0b69fbc685dd426670d6e7ce84a71e2f3'
    retained_content = 'b24422e2d96a4e9ab88d882d76f2cff2baec28b71cbf5f443f19b366d3fd8510'
    historical_source_used = False
    def check_identity(identity):
        nonlocal historical_source_used
        path = (root / identity['path']).resolve()
        require(path.is_relative_to(root) and path.is_file(), 'scaling bound file missing or outside artifact')
        raw = path.read_bytes()
        if (identity['path'] == 'src/msgbranch/project.py' and
                (len(raw) != identity['bytes'] or sha256(raw).hexdigest() != identity['sha256'])):
            # Only this exact reviewed repair may refer to the exact captured
            # measured source. No archived source is imported or executed.
            require(identity['sha256'] == old_project and identity['bytes'] == 98206,
                    'scaling bound file bytes changed: original project source differs')
            require(sha256(raw).hexdigest() == reviewed_project,
                    'scaling bound file bytes changed: unreviewed current project source')
            require(association_path.is_file(), 'scaling historical association missing')
            association = json.loads(association_path.read_text(encoding='utf-8'))
            expected = dict(run_id='20261021T060604257155Z', measured_source=captured_source,
                measured_sha256=old_project, current_source=identity['path'],
                current_sha256=reviewed_project, receipt_sha256=retained_receipt,
                receipt_content_sha256=retained_content,
                scope='Retained measurements of the captured source, not timings of the current unpack/admission repair.')
            require(association == expected, 'scaling historical association changed')
            selected = root / 'results/project-scaling.json'
            require(sha256(selected.read_bytes()).hexdigest() == retained_receipt,
                    'scaling retained receipt bytes changed')
            content = json.dumps(scaling, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            require(sha256(content).hexdigest() == retained_content,
                    'scaling retained receipt content changed')
            path = (root / captured_source).resolve()
            require(path.is_relative_to(root) and path.is_file(), 'scaling captured source missing')
            raw = path.read_bytes()
            historical_source_used = True
        require(len(raw) == identity['bytes'] and sha256(raw).hexdigest() == identity['sha256'],
                'scaling bound file bytes changed: ' + identity['path'])

    expected_sources = {'src/msgbranch/__init__.py', 'src/msgbranch/project.py', 'src/msgbranch/runtime.py',
                        'scripts/project_scaling.py', 'scripts/_repo_bootstrap.py', 'pyproject.toml'}
    require(set(scaling['source_identity']) == expected_sources, 'scaling source coverage')
    for name, identity in scaling['source_identity'].items():
        require(identity['path'] == name, 'scaling source identity path')
        check_identity(identity)
    expected_grid = [(shape, calls) for shape in design['shapes'] for calls in design['calls']]
    records = scaling['records']
    require([(row['shape'], row['calls']) for row in records] == expected_grid, 'scaling grid/order')
    previous_end = started
    for record in records:
        size = record['calls']
        repeated = record['shape'] == 'repeated-message'
        lookups, hits = (1, size - 1) if repeated else (size, 0)
        require(record['repeats'] == len(record['raw']) == 3, 'scaling repeat count')
        require(set(record['fixture_identity']) == {'source', 'catalog'}, 'scaling fixture coverage')
        for kind, filename in (('source', 'app.py'), ('catalog', 'messages.po')):
            identity = record['fixture_identity'][kind]
            expected = f"evidence/project-scaling/{scaling['run_id']}/inputs/{'repeated' if repeated else 'unique'}/{size}/{filename}"
            require(identity['path'] == expected, 'scaling fixture identity path')
            check_identity(identity)
        for repeat, row in enumerate(record['raw']):
            require(row['repeat'] == repeat and row['calls'] == row['findings'] == size,
                    'scaling raw call/repeat accounting')
            require(row['unique_runtime_lookup_sets'] == lookups and row['runtime_lookup_cache_hits'] == hits,
                    'scaling raw cache accounting')
            require(row['errors'] == row['unknown'] == 0 and row['selected_patterns'] == 3 * size,
                    'scaling raw classification accounting')
            require(all(math.isfinite(row[key]) and row[key] > 0 for key in ('wall_ms', 'peak_kib')),
                    'scaling positive finite measurements')
            begin, end = stamp(row['started_at_utc']), stamp(row['completed_at_utc'])
            require(previous_end <= begin < end <= completed, 'scaling observation UTC order')
            previous_end = end
        require(record['median_wall_ms'] == statistics.median(row['wall_ms'] for row in record['raw']) and
                record['median_peak_kib'] == statistics.median(row['peak_kib'] for row in record['raw']),
                'scaling raw/median mismatch')
        require(record['runtime_lookup_sets'] == lookups and record['cache_hits'] == hits and
                record['errors'] == record['unknown'] == 0 and record['selected_patterns'] == 3 * size,
                'scaling summary accounting')
    return {'status': 'pass', 'observations_recounted': 24, 'groups_recounted': 8,
            'source_files_bound': len(expected_sources), 'fixture_files_bound': 16,
            'run_id': scaling['run_id'], 'captured_measured_source': historical_source_used,
            'scope': ('Retained receipt and captured measured source; reviewed current repair is associated, not remeasured'
                      if historical_source_used else 'Receipt accounting and current byte identity; no new scans')}

def audit_holdout(holdout):
    """Recount either an archived frozen check or an explicit current regression."""
    summary, records = holdout['summary'], holdout['records']
    require(summary['projects'] == len(records) == 2, 'holdout project accounting')
    for key in ('findings', 'clean', 'errors', 'unknown'):
        target = 'call_catalog_findings' if key == 'findings' else key
        require(summary[target] == sum(r['flow_summary'][key] for r in records), 'holdout ' + key)
    runtime = [item for row in records for item in row['runtime']]
    require(summary['runtime_executions'] == len(runtime) == 10, 'holdout runtime execution')
    require(summary['runtime_errors'] == sum(item['status'] == 'error' for item in runtime), 'holdout runtime errors')
    frozen = holdout['freeze']['expected'] == holdout['freeze']['actual']
    require(summary['analyzer_hashes_match_freeze'] == frozen, 'holdout freeze accounting')
    require(summary['status'] == 'pass', 'holdout validation failed')
    mode = summary.get('evaluation_mode', 'frozen-source')
    if mode == 'current-regression':
        require(summary['qualification_status'] == ('error' if summary['errors'] else ('unknown' if summary['unknown'] else 'clean')), 'holdout qualification scope')
        expected = {
            'solaar': {('singular', 'No paired devices.', 'unknown'), ('plural', '%(count)s paired device.', 'clean')},
            'virt-manager': {('plural', 'Waiting %(minutes)d minute for the installation to complete.', 'clean')},
        }
        require({r['case'] for r in records} == set(expected), 'holdout case identities')
        for row in records:
            findings = row['findings']
            require(len(findings) == row['flow_summary']['findings'], 'holdout finding accounting')
            for status, key in (('clean', 'clean'), ('error', 'errors'), ('unknown', 'unknown')):
                require(row['flow_summary'][key] == sum(f['status'] == status for f in findings), 'holdout per-case classification')
            actual = {(f['call']['kind'], f['call']['singular'], f['status']) for f in findings}
            require(actual == expected[row['case']] and len(findings) == len(actual), 'holdout boundary contract')
            require([r['count'] for r in row['runtime']] == holdout['selection']['counts'], 'holdout count selection')
            for finding in findings:
                if finding['status'] == 'unknown':
                    require(finding.get('witnesses') and all(w['qualification'].get('reason') == 'unresolved use reachability'
                            and (w.get('flow') or {}).get('reachable') is None for w in finding['witnesses']), 'holdout unexplained unknown')
            identity = row['source_identity']
            require(identity.get('commit') and identity.get('repository') and all(identity.get(key) for key in
                    ('source_sha256', 'catalog_sha256', 'provenance_sha256')), 'holdout source identity missing')
        require(all(r['status'] == 'ok' and r.get('matches_expected') is True and r['output'] == r['expected_output'] for r in runtime), 'holdout native boundary oracle')
        require(holdout['checks'] and all(holdout['checks'].values()), 'holdout regression checks')
    else:
        require(mode == 'frozen-source', 'holdout unknown evaluation mode')
        require(frozen and summary['clean'] == 3 and summary['errors'] == summary['unknown'] == 0, 'holdout frozen classification')
        require(all(r['status'] == 'ok' for r in runtime), 'holdout frozen runtime')
    return {'evaluation_mode': mode, 'findings': summary['call_catalog_findings'], 'runtime_executions': len(runtime)}

def audit_project_qualification(project):
    """Recount transitions; conservative unknowns are evidence, not regressions by definition."""
    summary = project['summary']
    rows = project['controls'] + project['field_slices']
    keys = ('unknown_to_clean', 'unknown_to_error', 'clean_to_unknown', 'error_to_unknown', 'other_changes')
    totals = dict.fromkeys(keys, 0)
    current = summary.get('evaluation_mode') == 'current-source'
    for row in rows:
        findings = row['findings']
        require(row['summary']['findings'] == len(findings), 'project finding accounting')
        for status, key in (('clean', 'clean'), ('error', 'errors'), ('unknown', 'unknown')):
            require(row['summary'][key] == sum(f['status'] == status for f in findings), 'project classification accounting')
        if current:
            direct = row['direct_findings']
            require(len(direct) == len(findings) == row['direct_summary']['findings'], 'project direct/flow cardinality')
            actual = dict.fromkeys(keys, 0)
            for before, after in zip(direct, findings, strict=True):
                require((before['call'], before.get('catalog')) == (after['call'], after.get('catalog')), 'project direct/flow identity')
                if before['status'] != after['status']:
                    key = before['status'] + '_to_' + after['status']
                    actual[key if key in actual else 'other_changes'] += 1
                    if after['status'] == 'unknown':
                        require(after.get('reason') or any(w['qualification'].get('reason') for w in after.get('witnesses', [])), 'project unexplained tightening')
            require(row['ablation'] == actual, 'project transition accounting')
            for status, key in (('clean', 'clean'), ('error', 'errors'), ('unknown', 'unknown')):
                require(row['direct_summary'][key] == sum(f['status'] == status for f in direct), 'project direct classification accounting')
        for key in keys:
            require(row['ablation'][key] >= 0, 'project negative transition count')
            totals[key] += row['ablation'][key]
    require(summary['ablation'] == totals, 'project total transition accounting')
    for key in ('findings', 'clean', 'errors', 'unknown', 'selected_patterns'):
        target = 'call_catalog_findings' if key == 'findings' else key
        require(summary[target] == sum(r['summary'][key] for r in rows), 'project total ' + key)
    for key in ('clean', 'errors', 'unknown', 'selected_patterns'):
        require(summary['direct_' + key] == sum(r['direct_summary'][key] for r in rows), 'project direct total ' + key)
    require(summary['errors'] > 0 and summary['unknown'] > 0, 'project audit classification')
    require(summary['direct_unknown'] > summary['unknown'], 'project flow analysis did not reduce unknowns')
    require(totals['unknown_to_clean'] > 0 and totals['unknown_to_error'] > 0, 'project flow recovery')
    return {'findings': summary['call_catalog_findings'], 'transitions': totals, 'current_direct_records_recounted': current}

def audit_study(study):
    families = load(study + '.json')
    summary = load(study + '-summary.json')
    selected = {x['case']: x for x in load(study + '-selected.json')}
    ids = {f['id']: f for f in families}
    require(len(ids) == len(families) == summary['families'], study + ': duplicate/missing family')
    seen = defaultdict(set)
    failures = defaultdict(set)
    signatures = defaultdict(set)
    observed = {}
    total = 0
    with gzip.open(R / (study + '-runs.jsonl.gz'), 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            cid, n = row['case'], row['n']
            require(cid in ids, study + ': unknown family')
            require(n not in seen[cid], study + ': repeated input')
            require(0 <= n < ids[cid]['domain_size'], study + ': out-of-domain input')
            seen[cid].add(n)
            signatures[cid].add(row['signature'])
            if row['status'] == 'error':
                failures[cid].add(n)
            require(row['status'] in ('ok', 'error'), study + ': unexpected raw status')
            if n in ids[cid]['representatives']:
                observed[(cid, n)] = (row['status'], row['output'], row['error'])
            total += 1
    keys = ['ordinary2_detects', 'ordinary7_detects', 'branch_only_detects',
            'source_only_detects', 'product_detects', 'equal_budget_even_detects', 'babel_alarm']
    active = []
    for f in families:
        cid = f['id']
        fs = failures[cid]
        require(len(seen[cid]) == f['domain_size'], cid + ': missing domain inputs')
        require(len(fs) == f['failures'], cid + ': wrong failure count')
        require(f['active_mutation'] == (f['category'] == 'mutation' and bool(fs)), cid + ': wrong activation')
        require(len(signatures[cid]) == f['predicate_signature_count'], cid + ': signature accounting')
        values = {
            'ordinary2_detects': [1, 2],
            'ordinary7_detects': [0, 1, 2, 5, 11, 21, 100],
            'branch_only_detects': f['branch_only_values'],
            'source_only_detects': f['source_only_values'],
            'product_detects': f['representatives'],
            'equal_budget_even_detects': f['even_values'],
        }
        for key, vv in values.items():
            require(f[key] == bool(fs.intersection(vv)), cid + ': incorrect ' + key)
        require(f['budget'] == len(f['representatives']), cid + ': budget mismatch')
        record = selected[cid]
        require(record['plan']['representatives'] == f['representatives'], cid + ': plan/witness mismatch')
        require(len(record['selected']) == f['budget'], cid + ': replay count')
        for row in record['selected']:
            require((row['status'], row['output'], row['error']) == observed[(cid, row['n'])], cid + ': selected/raw mismatch')
        N, K, b = f['domain_size'], len(fs), f['budget']
        p = 0.0 if K == 0 else 1.0 - math.comb(N - K, b) / math.comb(N, b)
        require(math.isclose(p, f['random_detection_probability_exact'], abs_tol=1e-12), cid + ': random probability')
        require(len(f['random_trials']) == summary['random_trials_per_family'], cid + ': random repetitions')
        for trial in f['random_trials']:
            require(len(trial['values']) == len(set(trial['values'])) == b, cid + ': random budget')
            require(trial['detects'] == bool(fs.intersection(trial['values'])), cid + ': random detection')
        if f['active_mutation']:
            active.append(f)
    require(total == summary['native_reference_comparisons'], study + ': native comparison count')
    require(total == summary['exhaustive_signature_checks'], study + ': signature comparison count')
    require(len(active) == summary['active_mutations'], study + ': active count')
    require(Counter(f['category'] for f in families)['mutation'] - len(active) == summary['inactive_mutations'], study + ': inactive count')
    for key in keys:
        require(sum(f[key] for f in active) == summary['active_mutation_detection'][key], study + ': baseline total ' + key)
    for target, field in [('selected_executions','budget'), ('planning_calls','planning_calls'), ('cell_evaluations','cell_evaluations')]:
        require(sum(f[field] for f in families) == summary[target], study + ': ' + target)
    require(sum(t['detects'] for f in active for t in f['random_trials']) == summary['random_total_hits'], study + ': random hits')
    return {'families': len(families), 'raw_outcomes_recounted': total,
            'active_mutations': len(active), 'native_selected_outcomes_matched': sum(f['budget'] for f in families),
            'baseline_and_random_trial_labels_recomputed': True, 'status': 'pass'}

def main():
    studies = {s: audit_study(s) for s in ['validation', 'confirmation']}
    oh = load('openhangar-runs.json')
    ohs = load('openhangar-summary.json')
    require(len(oh) == ohs['native_boundary_executions'], 'OpenHangar execution count')
    require(all(x['native_adapter_equal'] for x in oh), 'OpenHangar disagreement')
    for v in ['before', 'after']:
        require(sum(x['version'] == v and x['status'] == 'error' for x in oh) == ohs[v+'_failing_contexts'], 'OpenHangar ' + v)
    bed = load('bedrock-runs.json')
    beds = load('bedrock-summary.json')
    require(len(bed) == beds['upstream_assertions'], 'Bedrock assertion count')
    require(all(x['expected'] == x['direct'] == x['observed'] for x in bed), 'Bedrock output mismatch')
    costs = load('costs.json')
    for case in costs['cases']:
        for method, median in case['median_ms'].items():
            actual = statistics.median(row[method + '_ms'] for row in case['raw'])
            require(actual == median, 'Cost median mismatch')
    xr = load('xrpldashboard-runs.json')
    xrs = load('xrpldashboard-summary.json')
    require(len(xr) == xrs['native_boundary_executions'], 'xrpldashboard execution count')
    require(sum(x['version'] == 'before' and x['status'] == 'error' for x in xr) == xrs['before_failures'], 'xrpldashboard before')
    require(sum(x['version'] == 'after' and x['status'] == 'error' for x in xr) == xrs['after_failures'], 'xrpldashboard after')
    require(xrs['ordinary_count_one_detects'] and xrs['unique_over_ordinary_count_one'] == 0, 'xrpldashboard baseline classification')
    lh = load('localhero-core.json')
    lhs = load('localhero-core-summary.json')
    for pop in ['controls', 'validation', 'confirmation', 'openhangar']:
        rows = [x for x in lh if x['population'] == pop]
        require(len(rows) == lhs[pop]['units'], 'LocalHero unit accounting')
        require(sum(x['error'] for x in rows) == lhs[pop]['errors'], 'LocalHero error accounting')
        require(sum(x['hint'] for x in rows) == lhs[pop]['hints'], 'LocalHero hint accounting')
    screen = load('public-fix-screen-summary.json')
    require(screen['candidates'] == 20 and screen['executed_historical_repairs'] == 4, 'public screen accounting')
    require(screen['executed_detected_by_ordinary_1_2'] == 3 and screen['executed_detected_by_cheap_nonproduct'] == 4 and screen['executed_requiring_guard_product'] == 0, 'public screen baseline classification')
    babel_cli = load('babel-cli.json')
    require(babel_cli['status'] == 'executed', 'Babel CLI not executed')
    bsum = babel_cli['summary']
    require(bsum['catalogs'] == bsum['cli_success'] + bsum['cli_failures'], 'Babel CLI input accounting')
    require(bsum['cli_success'] == bsum['functional_equal'] and bsum['all_outputs_equal'] == bsum['catalogs'], 'Babel CLI output accounting')
    require(bsum['format_diagnostics_agree'], 'Babel CLI diagnostic accounting')
    require(bsum['format_mismatch_rejected'] and bsum['invalid_encoding_rejected'], 'Babel CLI controls')
    azm = load('azm-build.json')
    require(azm['before']['falls_back_to_source'] and azm['after']['translated'], 'AZM build boundary')
    flow = load('flow-validation.json')
    fsum = flow['summary']
    require(fsum['status'] == 'pass', 'flow validation failed')
    require(fsum['flow_exact'] == fsum['controls'], 'flow validation exactness')
    require(fsum['flow_false_positive_controls'] == 0, 'flow validation false positives')
    require(fsum['flow_false_negative_controls'] == 0, 'flow validation false negatives')
    require(fsum['direct_exact'] < fsum['flow_exact'], 'flow ablation did not improve exactness')
    holdout = load('holdout.json')
    hsum = holdout['summary']
    holdout_accounting = audit_holdout(holdout)
    project = load('project-audit.json')
    psum = project['summary']
    project_accounting = audit_project_qualification(project)
    scaling = load('project-scaling.json')
    audit_project_scaling(scaling)
    stats = load('statistical-analysis.json')
    require(stats['validation']['methods']['product']['hits'] == 52, 'validation statistics')
    require(stats['confirmation']['methods']['product']['hits'] == 54, 'confirmation statistics')
    wc = load('weblate-core.json')
    ws = load('weblate-core-summary.json')
    for pop in ['controls', 'validation', 'confirmation', 'openhangar']:
        for setting, stats in ws[pop].items():
            rows = [x for x in wc if x['population'] == pop and x['strict'] == (setting == 'strict')]
            require(len(rows) == stats['units'], 'Weblate unit accounting')
            require(sum(x['alarm'] for x in rows) == stats['alarms'], 'Weblate alarm accounting')
            for cat, count in stats['by_category'].items():
                group = [x for x in rows if x['category'] == cat]
                require(len(group) == count['units'] and sum(x['alarm'] for x in group) == count['alarms'], 'Weblate category accounting')
    report = {'status': 'pass', 'studies': studies,
              'openhangar_outcomes_recounted': len(oh), 'bedrock_assertions_matched': len(bed),
              'cost_medians_recomputed': len(costs['cases']) * 3,
              'weblate_component_unit_records_recounted': len(wc),
              'localhero_component_unit_records_recounted': len(lh),
              'xrpldashboard_outcomes_recounted': len(xr),
              'public_fix_candidates_recounted': screen['candidates'],
              'babel_cli_catalogs_recounted': bsum['catalogs'],
              'flow_validation_controls_recounted': fsum['controls'],
              'flow_validation_runtime_executions_recounted': fsum['runtime_executions'],
              'project_audit_findings_recounted': psum['call_catalog_findings'],
              'holdout_findings_recounted': hsum['call_catalog_findings'],
              'holdout_runtime_executions_recounted': hsum['runtime_executions'],
              'holdout_accounting': holdout_accounting,
              'project_qualification_accounting': project_accounting,
              'project_scaling_records_recounted': len(scaling['records']),
              'azm_build_boundary_recounted': True,
              'scope': 'Independent result accounting and selected/raw consistency; not an independent implementation or proof of correctness'}
    (R / 'result-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-scaling-only', action='store_true', help='check the scaling receipt only; write no results')
    if parser.parse_args().project_scaling_only:
        print(json.dumps(audit_project_scaling(load('project-scaling.json')), indent=2))
    else:
        main()
