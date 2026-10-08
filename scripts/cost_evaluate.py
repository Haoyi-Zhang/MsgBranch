"""Paired charged-cost measurements, with no artificial route delay.

Every observation includes planning plus replay, not just retained test count.
Native all-count testing is intentionally included: direct local formatters can
be cheaper than a planner. Catalog loading/compilation is shared, reported apart.
No benchmark timing is a claim about an unexecuted web route.
"""
from pathlib import Path
from io import BytesIO
from time import perf_counter_ns
import json,statistics,platform,gettext,gc
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.program import Program,representatives
from msgbranch.partition import plan_partition
from msgbranch.runtime import CatalogRuntime
R=Path(__file__).resolve().parents[1]
CASES=['en-0','ru-2','ar-3','ja-0']

def observe(fn):
    start=perf_counter_ns();value=fn();return (perf_counter_ns()-start)/1e6,value

def native_all(fn,N):
    failures=[]
    for n in range(N+1):
        try:fn(n)
        except (KeyError,TypeError,ValueError):failures.append(n)
    return failures

def main():
    records=[]
    for cid in CASES:
        folder=R/'data/validation'/cid
        start=perf_counter_ns();p=Program((folder/'mutant.py').read_text());rt=CatalogRuntime(folder/'messages.po')
        shared_ms=(perf_counter_ns()-start)/1e6
        t=gettext.GNUTranslations(BytesIO(rt.mo));ns={'gettext':t.gettext,'ngettext':t.ngettext}
        exec(compile(p.source,'<trusted-cost-fixture>','exec'),ns);fn=ns['message']
        for high in (200,1000,10000):
            def partition():
                q=plan_partition(p,rt,high=high)
                tests=[p.run(rt,n) for n in q.representatives]
                return q,tests
            def old():
                values,unknown=representatives(p,rt,list(range(high+1)))
                return values,[p.run(rt,n) for n in values]
            # Warm all paths; rotate measurement order to reduce order bias.
            partition();old();native_all(fn,high)
            raw=[]
            for repeat in range(5):
                actions={'product':partition,'exhaustive_adapter':old,'native_all':lambda:native_all(fn,high)}
                keys=list(actions);keys=keys[repeat%3:]+keys[:repeat%3]
                row={'repeat':repeat}
                for key in keys:
                    ms,value=observe(actions[key]);row[key+'_ms']=ms
                raw.append(row)
            q,tests=partition()
            med={key:statistics.median(row[key+'_ms'] for row in raw) for key in actions}
            delta=max(0.,(med['product']-med['native_all'])/(high+1-len(tests))) if len(tests)<high+1 else None
            records.append({'case':cid,'domain_size':high+1,'shared_setup_ms':shared_ms,
                'cell_evaluations':q.cell_evaluations,'boundary_planning_calls':q.planning_calls,'retained':len(tests),
                'median_ms':med,'native_break_even_additional_ms_per_expensive_call':delta,
                'raw':raw})
    out={'scope':'CPU local boundary microbenchmark; no downstream service/route delays simulated',
         'repeats':5,'timer':'perf_counter_ns','python':platform.python_version(),
         'platform':platform.platform(),'cases':records,
         'note':'Additional cost break-even is algebraic: (Tproduct-Tnative)/(N-retained), floored at zero. It is not observed application speedup.'}
    (R/'results/costs.json').write_text(json.dumps(out,indent=2)+'\n')
    for r in records:print(r['case'],r['domain_size'],r['boundary_planning_calls'],r['retained'],r['median_ms'])
if __name__=='__main__':main()
