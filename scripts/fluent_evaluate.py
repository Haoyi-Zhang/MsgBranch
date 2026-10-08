"""Deterministic synthetic controls and separately labeled runtime-contract probes."""
from __future__ import annotations
from decimal import Decimal
from pathlib import Path
import json, time, statistics, sys

from fluent.runtime.bundle import FluentBundle
from fluent.runtime.fallback import FluentLocalization, AbstractResourceLoader
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.fluent_adapter import Trace, parse_bounded, candidate_values, scalar, signature, literal_calls

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data/fluent'; DATA.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT/'results'

class Loader(AbstractResourceLoader):
    def __init__(self, mapping): self.mapping = mapping
    def resources(self, locale, resource_ids):
        if locale in self.mapping: yield [parse_bounded(self.mapping[locale])]


def run():
    cases = []
    def add(name, category, text, values, supplier, expected, locale='en'):
        cases.append((name,category,text,values,supplier,expected,locale))
    add('branch-omission','legitimate', '''m = { $n ->
    [one] One item
   *[other] { $n } items for { $owner }
}
''', list(range(201)), lambda n: {'n':n} if n==1 else {'n':n,'owner':'A'}, lambda n: 'One item' if n==1 else f'{n} items for A')
    add('reorder','legitimate','m = { $b }, { $a }\n',[1,2],lambda n:{'a':'A','b':'B'},lambda n:'B, A')
    add('numeric-explicit','legitimate','''m = { $n ->
    [100] boundary
   *[other] ordinary
}
''',list(range(201)),lambda n:{'n':n},lambda n:'boundary' if n==100 else 'ordinary')
    add('string-default','legitimate','''m = { $kind ->
    [ready] Ready
   *[other] Waiting
}
''',['ready','other','unknown'],lambda n:{'kind':n},lambda n:'Ready' if n=='ready' else 'Waiting')
    add('message-reference','legitimate','''m = { child }
child = { $n ->
    [one] One
   *[other] { $n } items
}
''',list(range(201)),lambda n:{'n':n},lambda n:'One' if n==1 else f'{n} items')
    add('term-default','legitimate','''-brand = { $case ->
    [formal] Example Corporation
   *[other] Example
}
m = { -brand }
''',[1,2],lambda n:{},lambda n:'Example')
    add('term-explicit','legitimate','''-brand = { $case ->
    [formal] Example Corporation
   *[other] Example
}
m = { -brand(case: "formal") }
''',[1,2],lambda n:{},lambda n:'Example Corporation')
    add('arabic-categories','legitimate','''m = { $n ->
    [zero] zero
    [one] one
    [two] two
    [few] few
    [many] many
   *[other] other
}
''',list(range(201)),lambda n:{'n':n}, lambda n: 'zero' if n==0 else 'one' if n==1 else 'two' if n==2 else 'few' if 3<=n%100<=10 else 'many' if 11<=n%100<=99 else 'other',locale='ar')
    add('missing-at-100','mutation','''m = { $n ->
    [100] { $owner }
   *[other] OK
}
''',list(range(201)),lambda n:{'n':n},lambda n:None if n==100 else 'OK')
    add('reference-missing-at-100','mutation','''m = { $n ->
    [100] { child }
   *[other] OK
}
child = { $owner }
''',list(range(201)),lambda n:{'n':n},lambda n:None if n==100 else 'OK')
    add('missing-supplier-at-100','mutation','''m = { $n ->
    [one] One
   *[other] { $owner }
}
''',list(range(201)),lambda n:{'n':n} if n==100 else {'n':n,'owner':'A'},lambda n: None if n==100 else 'One' if n==1 else 'A')
    add('number-type-at-100','mutation','''m = { $n ->
    [one] One
   *[other] { NUMBER($count) }
}
''',list(range(201)),lambda n:{'n':n,'count':'bad' if n==100 else n},lambda n:None if n==100 else 'One' if n==1 else str(n))
    add('decimal-exact','runtime-contract-probe','''m = { $n ->
    [1] exact
   *[other] other
}
''',[1,1.0,Decimal('1'),Decimal('1.0')],lambda n:{'n':n},lambda n:'exact')
    add('formatted-plural','runtime-contract-probe','''m = { NUMBER($n, minimumFractionDigits: 1) ->
    [one] one
   *[other] other
}
''',[1,1.0,Decimal('1'),Decimal('1.0')],lambda n:{'n':n},lambda n:'other')
    allrows, table = [], []
    for name,category,text,values,supplier,expected,locale in cases:
        (DATA/f'{name}.ftl').write_text(text)
        bundle=FluentBundle([locale],use_isolating=False); bundle.add_resource(parse_bounded(text))
        pattern=bundle.get_message('m').value
        selected,branch_selected,rows={}, {}, []
        start=time.perf_counter_ns()
        for n in values:
            args=supplier(n)
            direct,errors=bundle.format_pattern(pattern,args)
            with Trace() as t:
                actual,observed=bundle.format_pattern(pattern,args)
            assert actual==direct and [(type(e),str(e)) for e in errors]==[(type(e),str(e)) for e in observed]
            trace=t.result(); exp=expected(n)
            alarm=bool(observed) or (exp is not None and actual!=exp)
            assert bool(observed)==(exp is None) if category!='runtime-contract-probe' else True
            if category=='legitimate': assert actual==exp and not observed
            row={'case':name,'category':category,'input':scalar(n),'input_type':type(n).__name__,
                 'args':{k:scalar(v) for k,v in args.items()},'output':str(actual),
                 'expected':exp,'alarm':alarm,'trace':trace,'direct_equivalent':True}
            rows.append(row); allrows.append(row)
            selected.setdefault(signature(trace,args),row)
            branch_selected.setdefault(signature(trace,args,False),row)
        elapsed=(time.perf_counter_ns()-start)/1e6
        ordinary=[r for r in rows if r['input_type']=='int' and r['input'] in (1,2)]
        table.append({'case':name,'category':category,'runs':len(rows),'selected':len(selected),
                      'branch_selected':len(branch_selected),'ordinary_detects':any(r['alarm'] for r in ordinary),
                      'branch_detects':any(r['alarm'] for r in branch_selected.values()),
                      'call_detects':any(r['alarm'] for r in selected.values()),
                      'parse_errors':0,'observed_alarm_runs':sum(r['alarm'] for r in rows),
                      'selected_inputs':[r['input'] for r in selected.values()],
                      'candidate_keys':candidate_values(text,'m',200), 'wall_ms':round(elapsed,4)})
    # Replays the documented high-level API, including its permitted fallback.
    mapping={'de':'second-string = Eine Übersetzung\nbroken = { $missing }\n',
             'en-US':'my-first-string = Fluent can be easy\nsecond-string = An original string\nbroken = English recovery\n'}
    loader=Loader(mapping); loc=FluentLocalization(['de','en-US'],['main.ftl'],loader)
    docs=[]
    for key,expected in [('my-first-string','Fluent can be easy'),('second-string','Eine Übersetzung'),('absent','absent'),('broken','missing')]:
        with Trace() as t: val=loc.format_value(key)
        assert val==expected
        docs.append({'id':key,'output':val,'trace':t.result()})
    recovered=literal_calls('l10n.format_value("my-first-string")\nl10n.format_value(key, supplied)\n')
    assert [r['status'] for r in recovered]==['literal','unknown']
    summary={'commit':'e95b07ea07966dec064d09398a265222742bcfa2','families':len(table),
             'legitimate':8,'mutations':4,'runtime_contract_probe_families':2,
             'runs':len(allrows),'profile_differential_checks':len(allrows),'profile_disagreements':0,
             'documented_api_calls':4,'mutation_detection':{k:sum(r[k] for r in table if r['category']=='mutation') for k in ['ordinary_detects','branch_detects','call_detects']},
             'legitimate_false_alarms':sum(r['call_detects'] for r in table if r['category']=='legitimate'),
             'runtime_contract_alarm_runs':sum(r['alarm'] for r in allrows if r['category']=='runtime-contract-probe'),
             'maintainer_confirmation':False,'downstream_application_cases':0,
             'scope':'synthetic controls and documentation/runtime probes; not application defect yield'}
    for file,obj in [('fluent-summary.json',summary),('fluent-cases.json',table),('fluent-runs.json',allrows),('fluent-documentation.json',docs),('fluent-call-recovery.json',recovered)]:
        (RESULTS/file).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':run()
