from pathlib import Path
import json,hashlib
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.runtime import CatalogRuntime
from msgbranch.weblate_core import check_catalog
R=Path(__file__).resolve().parents[1]
rows=[]
for population,manifest in [('controls','data/control-manifest.json'),('validation','data/validation/manifest.json'),('confirmation','data/confirmation/manifest.json')]:
    cases=json.loads((R/manifest).read_text())
    if isinstance(cases,dict):cases=cases.get('cases',cases.get('families',cases))
    for c in cases:
        rt=CatalogRuntime(R/c['catalog'])
        for strict in (False,True):
            checks=check_catalog(rt.catalog,strict=strict)
            rows.append({'population':population,'case':c['id'],'category':c.get('category',c.get('kind')),
                         'strict':strict,'alarm':any(r['alarm'] for r in checks),'checks':checks})
for v in ('before','after'):
    for loc in ('fr','nl'):
        rt=CatalogRuntime(R/'data/openhangar'/v/f'{loc}.po')
        checks=check_catalog(rt.catalog)
        rows.append({'population':'openhangar','case':v+'-'+loc,'category':v,'strict':False,
                     'alarm':any(r['alarm'] for r in checks),'checks':checks})
(R/'results/weblate-core.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
summary={}
for pop in ('controls','validation','confirmation','openhangar'):
    summary[pop]={}
    for strict in (False,True):
        if pop=='openhangar' and strict:continue
        selected=[r for r in rows if r['population']==pop and r['strict']==strict]
        summary[pop]['strict' if strict else 'default']={'units':len(selected),'alarms':sum(r['alarm'] for r in selected), 'by_category':{cat:{'units':sum(r['category']==cat for r in selected),'alarms':sum(r['alarm'] and r['category']==cat for r in selected)} for cat in sorted({r['category'] for r in selected},key=str)}}
summary['scope']='Weblate 5.13 Python percent/brace format comparison and plural-example source excerpts, with explicit fixture wiring; not full Weblate deployment or all checks.'
(R/'results/weblate-core-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
