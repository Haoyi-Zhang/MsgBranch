"""Replay exact OpenHangar Jinja expressions and their normalized call boundary."""
from pathlib import Path
from types import SimpleNamespace
import json
import platform
import jinja2
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.program import Program
from msgbranch.runtime import CatalogRuntime
from msgbranch.partition import plan_partition
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/openhangar'

def run():
    rows=[]; reports=[]; disagreements=[]
    p=Program((D/'adapter.py').read_text())
    for version in ('before','after'):
        for locale in ('fr','nl'):
            rt=CatalogRuntime(D/version/f'{locale}.po')
            env=jinja2.Environment(extensions=['jinja2.ext.i18n'])
            env.install_gettext_translations(rt.translator,newstyle=True)
            plan=plan_partition(p,rt,high=30)
            # Cheap baseline: ngettext caller's plural source must agree with the
            # stored plural id for the same singular key. This detects collisions
            # but a conflict alone is not a proven runtime defect in general.
            entry=rt.catalog.get('one day')
            plural_conflict=entry.id[1] != '%(n)s days'
            reports.append({'version':version,'locale':locale,'babel_checks':rt.checks,
                'plural_source_conflict':plural_conflict,'plan':plan.to_dict()})
            for field in ('med','sep'):
                template=env.from_string((D/f'{field}.jinja').read_text().rstrip('\n'))
                for n in range(31):
                    try:
                        output=template.render(**{field:SimpleNamespace(days_remaining=n)})
                        status,error='ok',None
                    except (KeyError,TypeError,ValueError) as exc:
                        output=None;status='error';error=f'{type(exc).__name__}: {exc}'
                    adapted=p.run(rt,n)
                    same=(status,output,error)==(adapted.status,adapted.output,adapted.error)
                    if not same:disagreements.append({'version':version,'locale':locale,'n':n,'field':field})
                    rows.append({'version':version,'locale':locale,'field':field,'n':n,
                        'status':status,'output':output,'error':error,'native_adapter_equal':same,
                        'lookups':adapted.lookups})
    failures=[r for r in rows if r['status']=='error']
    summary={'historical_repairs':1,'native_boundary_executions':len(rows),
             'native_adapter_disagreements':len(disagreements),
             'before_failing_contexts':sum(r['version']=='before' for r in failures),
             'after_failing_contexts':sum(r['version']=='after' for r in failures),
             'babel_alarms':sum(bool(r['babel_checks']) for r in reports),
             'ordinary_1_2_detects':any(r['version']=='before' and r['n'] in (1,2) for r in failures),
             'simple_plural_conflict_detects':any(r['version']=='before' and r['plural_source_conflict'] for r in reports),
             'partition_retains_failing_witness':all(any(r['version']==x['version'] and r['locale']==x['locale'] and r['n'] in x['plan']['representatives'] for r in failures) for x in reports if x['version']=='before'),
             'incremental_real_defects_over_strong_ordinary_baseline':0,
             'environment':{'python':platform.python_version(),'jinja2':jinja2.__version__}}
    (ROOT/'results/openhangar-runs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'results/openhangar-checks.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'results/openhangar-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    assert not disagreements and not summary['after_failing_contexts'],summary
    print(json.dumps(summary,indent=2))
    return summary
if __name__=='__main__':run()
