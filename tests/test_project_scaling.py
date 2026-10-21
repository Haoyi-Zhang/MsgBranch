"""Unit checks do not launch additional native timing observations.

The genuine performance evidence is produced only by scripts/project_scaling.py.
"""
from pathlib import Path
import json
import runpy
import sys
import tracemalloc

import pytest

from scripts import project_scaling as scaling
from scripts.audit_results import audit_project_scaling


def test_measurement_grid_and_cache_accounting_with_stub(tmp_path, monkeypatch):
    calls_seen = []

    def stub_observation(source, catalog):
        size = int(source.parent.name)
        repeated = source.parent.parent.name == 'repeated'
        calls_seen.append((repeated, size))
        return dict(wall_ms=float(len(calls_seen)), peak_kib=1.0,
                    calls=size, findings=size, selected_patterns=3 * size,
                    unique_runtime_lookup_sets=1 if repeated else size,
                    runtime_lookup_cache_hits=size - 1 if repeated else 0,
                    errors=0, unknown=0, started_at_utc=scaling.utc_now(),
                    completed_at_utc=scaling.utc_now())

    # Unit fixtures can reside outside the checkout; no results are published.
    monkeypatch.setattr(scaling, 'ROOT', tmp_path)
    monkeypatch.setattr(scaling, 'source_identity', lambda: {'unit_test_stub': True})
    monkeypatch.setattr(scaling, 'environment', lambda: {'unit_test_stub': True})
    monkeypatch.setattr(scaling, 'observation', stub_observation)
    result = scaling.evaluate(fixture_root=tmp_path / 'i')
    assert calls_seen == [(repeated, size) for repeated in (True, False)
                          for size in (1, 25, 100, 400) for _ in range(3)]
    assert result['design']['observations'] == len(calls_seen) == 24
    assert all(row['repeats'] == len(row['raw']) == 3 for row in result['records'])
    assert result['records'][3]['cache_hits'] == 399
    assert result['records'][7]['runtime_lookup_sets'] == 400
    assert result['records'][0]['median_wall_ms'] == 2.0
    assert all((tmp_path / identity['path']).is_file()
               for row in result['records'] for identity in row['fixture_identity'].values())


def test_budget_failure_does_not_measure(tmp_path, monkeypatch):
    monkeypatch.setattr(scaling, 'ROOT', tmp_path)
    monkeypatch.setattr(scaling, 'source_identity', lambda: {})
    monkeypatch.setattr(scaling, 'environment', lambda: {})
    monkeypatch.setattr(scaling, 'observation', lambda *args: pytest.fail('budget must stop observations'))
    with pytest.raises(TimeoutError, match='time budget'):
        scaling.evaluate(fixture_root=tmp_path / 'i', budget_seconds=0)


def test_observation_stops_trace_after_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('owned unit-test failure')
    monkeypatch.setattr(scaling, 'audit_project', fail)
    with pytest.raises(ValueError, match='owned unit-test failure'):
        scaling.observation(Path('unit-source'), Path('unit-catalog'))
    assert not tracemalloc.is_tracing()


def test_observation_refuses_existing_trace():
    tracemalloc.start()
    try:
        with pytest.raises(RuntimeError, match='fresh tracemalloc'):
            scaling.observation(Path('unit-source'), Path('unit-catalog'))
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def current_receipt():
    return json.loads((scaling.ROOT / 'results/project-scaling.json').read_text(encoding='utf-8'))


def test_retained_measurement_is_current_and_complete():
    # Read the genuine receipt; do not substitute unit stub timings for evidence.
    checked = audit_project_scaling(current_receipt())
    assert checked['observations_recounted'] == 24
    assert checked['fixture_files_bound'] == 16


@pytest.mark.parametrize('defect', ['missing_repeat', 'wrong_median', 'source_drift',
                                  'fixture_drift', 'missing_environment', 'extra_group',
                                  'wrong_cache', 'unavailable_classification', 'non_utc',
                                  'outside_path', 'wrong_domain', 'over_budget'])
def test_receipt_consumer_rejects_inconsistent_evidence(defect):
    result = current_receipt()
    first = result['records'][0]
    if defect == 'missing_repeat':
        first['raw'].pop()
    elif defect == 'wrong_median':
        first['median_wall_ms'] += 1
    elif defect == 'source_drift':
        result['source_identity']['src/msgbranch/project.py']['sha256'] = '0' * 64
    elif defect == 'fixture_drift':
        first['fixture_identity']['source']['sha256'] = '0' * 64
    elif defect == 'missing_environment':
        result['environment']['cpu_model'] = ''
    elif defect == 'extra_group':
        result['records'].append(first)
    elif defect == 'wrong_cache':
        first['raw'][0]['runtime_lookup_cache_hits'] += 1
    elif defect == 'unavailable_classification':
        first['raw'][0]['unknown'] = 1
    elif defect == 'non_utc':
        result['started_at_utc'] = '2026-10-21T00:00:00'
    elif defect == 'outside_path':
        first['fixture_identity']['source']['path'] = '../outside.py'
    elif defect == 'wrong_domain':
        result['max_count'] = 199
    elif defect == 'over_budget':
        result['campaign_elapsed_seconds'] = 901
    with pytest.raises(ValueError):
        audit_project_scaling(result)


def test_direct_paper_generator_reads_new_default_without_writing(monkeypatch):
    paper = scaling.ROOT.parent / 'paper'
    if not (paper / 'generate_tables.py').is_file():
        pytest.skip('standalone artifact checkout has no companion paper consumer')
    emitted = {}
    old_path = sys.path[:]
    monkeypatch.setattr(Path, 'write_text', lambda path, text, **kwargs: emitted.setdefault(path.name, text))
    try:
        runpy.run_path(str(paper / 'generate_tables.py'), run_name='__scaling_consumer_test__')
    finally:
        sys.path[:] = old_path
    rows = {(row['shape'], row['calls']): row for row in current_receipt()['records']}
    for shape, label in [('repeated-message', 'Repeated key'), ('unique-message', 'Unique keys')]:
        row = rows[(shape, 400)]
        assert f"{label} & 400 & {row['runtime_lookup_sets']} & {row['cache_hits']} & {row['median_wall_ms']:.1f} & {row['median_peak_kib']/1024:.2f}" in emitted['scaling.tex']
    assert emitted['scaling-values.tex'] == (paper / 'generated/scaling-values.tex').read_text(encoding='utf-8')


def test_direct_paper_generator_refuses_source_drift_before_writing(monkeypatch):
    paper = scaling.ROOT.parent / 'paper'
    if not (paper / 'generate_tables.py').is_file():
        pytest.skip('standalone artifact checkout has no companion paper consumer')
    loads = json.loads

    def injected_loads(text, *args, **kwargs):
        result = loads(text, *args, **kwargs)
        if isinstance(result, dict) and result.get('measurement_record_version') == 2:
            result['source_identity']['src/msgbranch/project.py']['sha256'] = '0' * 64
        return result

    old_path = sys.path[:]
    monkeypatch.setattr(json, 'loads', injected_loads)
    monkeypatch.setattr(Path, 'write_text', lambda *args, **kwargs: pytest.fail('stale receipt must not emit tables'))
    try:
        with pytest.raises(ValueError, match='bound file bytes changed'):
            runpy.run_path(str(paper / 'generate_tables.py'), run_name='__scaling_consumer_test__')
    finally:
        sys.path[:] = old_path
