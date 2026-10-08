"""Evaluate constructed controls; direct exec is ONLY for these trusted fixtures.

The public CLI never executes source. Here direct CPython is a separate, local
reference evaluator, not an independent human annotation or independent runtime.
"""
from pathlib import Path
import json
import time
import statistics
import platform
import shutil
from importlib import metadata
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.program import Program, representatives
from msgbranch.runtime import CatalogRuntime, placeholder_set_alarm
ROOT=Path(__file__).resolve().parents[1]
DOMAIN=list(range(201))

def reference(source, rt, n):
    # Explicitly trusted generated fixture, never user-provided arbitrary code.
    env={'gettext':rt.gettext,'_':rt.gettext,'ngettext':rt.ngettext,'pgettext':rt.pgettext,'npgettext':rt.npgettext}
    exec(compile(source,'<trusted-control>','exec'),env)
    rt.reset()
    try:
        output=env['message'](n)
        return {'status':'ok','output':output,'error_type':None}
    except (KeyError,TypeError,ValueError,IndexError,OverflowError) as exc:
        return {'status':'error','output':None,'error_type':type(exc).__name__}

def has_failure(result, spec):
    if result['status']=='error':
        return True
    if spec.get('contains')=='count' and result['status']=='ok':
        # Explicit synthetic intended output: numerical count must be rendered.
        return result['output'] != f"{result['n']} {'item' if result['n']==1 else 'items'}"
    return False

def run():
    manifest=json.loads((ROOT/'data/control-manifest.json').read_text())
    summaries=[]
    raw=[]
    for spec in manifest:
        source=(ROOT/spec['source']).read_text()
        rt=CatalogRuntime(ROOT/spec['catalog'])
        program=Program(source)
        t0=time.perf_counter_ns()
        selected,unknown=representatives(program,rt,DOMAIN)
        t1=time.perf_counter_ns()
        branch_only,_=representatives(program,rt,DOMAIN,call_aware=False)
        outcomes=[program.run(rt,n).to_dict() for n in DOMAIN]
        by_n={r['n']:r for r in outcomes}
        disagreements=[]
        if not spec['expected_unknown']:
            for n in DOMAIN:
                ref=reference(source,rt,n)
                actual=by_n[n]
                if ref['status']!=actual['status'] or ref['output']!=actual['output'] or (actual['status']=='error' and not actual['error'].startswith(ref['error_type']+':')):
                    disagreements.append(n)
            assert not disagreements,(spec['id'],disagreements[:5])
            actual_errors=[r['n'] for r in outcomes if r['status']=='error']
            assert actual_errors==spec['expected_error_counts'],(spec['id'],actual_errors)
        else:
            assert all(r['status']=='unknown' for r in outcomes),spec['id']
        source_is_percent='python-format' in next((m.flags for m in rt.catalog if m.id),set())
        named_source=any('%(' in str(m.id) for m in rt.catalog if m.id)
        equality=placeholder_set_alarm(rt.catalog) if source_is_percent and named_source else None
        times=[]
        for _ in range(7):
            start=time.perf_counter_ns()
            for n in selected:
                program.run(rt,n)
            times.append((time.perf_counter_ns()-start)/1e6)
        summary={'id':spec['id'],'category':spec['category'],'domain_size':len(DOMAIN),
                 'ordinary':[1,2],'branch_only':branch_only,'representatives':selected,
                 'unknown':unknown,'babel_alarm':bool(rt.checks),'babel_checks':rt.checks,
                 'placeholder_equality_alarm':equality,
                 'ordinary_detects':any(has_failure(by_n[n],spec) for n in [1,2]),
                 'branch_only_detects':any(has_failure(by_n[n],spec) for n in branch_only),
                 'call_aware_detects':any(has_failure(by_n[n],spec) for n in selected),
                 'bounded_exhaustive_detects':any(has_failure(r,spec) for r in outcomes),
                 'reference_disagreements':disagreements,
                 'planner_ms':(t1-t0)/1e6,'selected_execution_ms_median':statistics.median(times),
                 'selected_execution_ms_repeats':times}
        summaries.append(summary)
        raw.extend({'case':spec['id'],**r} for r in outcomes)
    output=ROOT/'results'
    output.mkdir(exist_ok=True)
    (output/'controls.json').write_text(json.dumps(summaries,indent=2,ensure_ascii=False)+'\n')
    with (output/'control-runs.jsonl').open('w') as fp:
        for row in raw:
            fp.write(json.dumps(row, ensure_ascii=True)+'\n')
    mut=[r for r in summaries if r['category']=='mutation']
    legit=[r for r in summaries if r['category']=='legitimate']
    totals={'families':len(summaries),'legitimate':len(legit),'mutations':len(mut),'unknown_families':sum(r['category']=='unknown' for r in summaries),
            'bounded_runs':len(raw),'direct_reference_checks':sum(r['category']!='unknown' for r in summaries)*len(DOMAIN),
            'reference_disagreements':sum(len(r['reference_disagreements']) for r in summaries),
            'mutation_detection':{k:sum(r[k] for r in mut) for k in ['ordinary_detects','branch_only_detects','call_aware_detects','babel_alarm']},
            'legitimate_false_alarms':{k:sum(bool(r[k]) for r in legit) for k in ['ordinary_detects','call_aware_detects','babel_alarm','placeholder_equality_alarm']},
            'selected_representatives':sum(len(r['representatives']) for r in summaries),
            'total_planner_ms':sum(r['planner_ms'] for r in summaries),
            'python':platform.python_version(),'babel':metadata.version('Babel'),'platform':platform.platform(),
            'gnu_msgfmt':shutil.which('msgfmt'),'weblate':'full application unavailable; source-component results in weblate-core-summary.json','fluent_runtime':'pinned source snapshot; evaluated separately in fluent-summary.json'}
    (output/'control-summary.json').write_text(json.dumps(totals,indent=2)+'\n')
    print(json.dumps(totals,indent=2))
    return summaries
if __name__=='__main__':run()
