"""Independently recount retained observations and witness/baseline outcomes.

This checker does not import the planner or its interpreter. It verifies result
accounting, not the mathematical correctness of those implementations. A fresh
--full CI run separately recomputes native comparisons.
"""
from pathlib import Path
from collections import Counter, defaultdict
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
    require(hsum['status'] == 'pass', 'holdout validation failed')
    require(hsum['projects'] == 2 and hsum['call_catalog_findings'] == 3, 'holdout accounting')
    require(hsum['clean'] == 3 and hsum['errors'] == 0 and hsum['unknown'] == 0, 'holdout classification')
    require(hsum['runtime_executions'] == 10 and hsum['runtime_errors'] == 0, 'holdout runtime execution')
    require(hsum['analyzer_hashes_match_freeze'], 'holdout analyzer freeze mismatch')
    project = load('project-audit.json')
    psum = project['summary']
    require(psum['errors'] > 0 and psum['unknown'] > 0, 'project audit classification')
    require(psum['direct_unknown'] > psum['unknown'], 'project flow analysis did not reduce unknowns')
    require(psum['ablation']['unknown_to_clean'] > 0, 'project flow clean recovery')
    require(psum['ablation']['unknown_to_error'] > 0, 'project flow error recovery')
    require(psum['ablation']['clean_to_unknown'] == 0 and psum['ablation']['error_to_unknown'] == 0, 'project flow regression')
    scaling = load('project-scaling.json')
    scaling_rows = {(row['shape'], row['calls']): row for row in scaling['records']}
    require(scaling_rows[('repeated-message', 400)]['runtime_lookup_sets'] == 1, 'project cache repeated')
    require(scaling_rows[('unique-message', 400)]['runtime_lookup_sets'] == 400, 'project cache unique')
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
              'project_scaling_records_recounted': len(scaling['records']),
              'azm_build_boundary_recounted': True,
              'scope': 'Independent result accounting and selected/raw consistency; not an independent implementation or proof of correctness'}
    (R / 'result-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
