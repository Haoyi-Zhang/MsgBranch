"""Executable regression oracles; no network, server, or arbitrary input exec."""
from pathlib import Path
from decimal import Decimal
import json
import subprocess
import sys
import pytest
from msgbranch.program import Program, Unsupported, representatives, requirements
from msgbranch.runtime import CatalogRuntime
from msgbranch.baselines import lookup_kind_conflicts
from msgbranch.fluent_adapter import Trace, parse_bounded, candidate_values, literal_calls
from fluent.runtime.bundle import FluentBundle

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=json.loads((ROOT/'data/control-manifest.json').read_text())

@pytest.mark.parametrize('spec',MANIFEST,ids=[s['id'] for s in MANIFEST])
def test_gettext_expected_boundaries(spec):
    p=Program((ROOT/spec['source']).read_text());r=CatalogRuntime(ROOT/spec['catalog'])
    selected,unknown=representatives(p,r,list(range(201)))
    if spec['expected_unknown']:
        assert unknown
        assert all(p.run(r,n).status=='unknown' for n in range(201))
    else:
        assert not unknown
        assert [n for n in range(201) if p.run(r,n).status=='error']==spec['expected_error_counts']
        assert all(p.run(r,n).status in ('ok','error') for n in selected)

@pytest.mark.parametrize('text',[
'def message(n):\n return gettext(key)\n',
'def message(n):\n return gettext("a") % external(n)\n',
'def message(n):\n for i in range(n):\n  return gettext("a")\n',
])
def test_unknown_never_silently_passes(text):
    r=CatalogRuntime(ROOT/'data/upstream/sphinx/ja.po')
    assert Program(text).run(r,1).status=='unknown'

@pytest.mark.parametrize('text',[
'def message(n,extra):\n return "x"\n',
'@unknown\ndef message(n):\n return "x"\n',
'def other(n):\n return "x"\n',
])
def test_unsupported_signature(text):
    with pytest.raises(Unsupported):Program(text)

def test_requirements_are_branch_local():
    assert requirements('One item','percent')==[]
    assert requirements('%(n)d items for %(owner)s','percent')==['n','owner']
    assert requirements('%c','percent') == ['@0']
    with pytest.raises(Unsupported): requirements('{x.y}','brace')

def test_lookup_kind_and_legitimate_missing_translation():
    folder=ROOT/'data/upstream/sphinx'
    before=(folder/'before.py').read_text();after=(folder/'after.py').read_text()
    for locale,alarm in [('ja',True),('de',False)]:
        rt=CatalogRuntime(folder/f'{locale}.po')
        rows=lookup_kind_conflicts(before,rt,overloaded_callees=('__',))
        assert len(rows)==1 and rows[0]['alarm']==alarm
        assert not lookup_kind_conflicts(after,rt,overloaded_callees=('__',))

@pytest.mark.parametrize('case',['compiler-empty-plural','fuzzy-fallback','intended-fallback'])
def test_fallback_is_recorded_not_guessed_from_language(case):
    s=next(s for s in MANIFEST if s['id']==case)
    p=Program((ROOT/s['source']).read_text());r=CatalogRuntime(ROOT/s['catalog'])
    rows=[p.run(r,n).to_dict() for n in [1,2]]
    assert all(row['status']=='ok' for row in rows)
    assert any(x['resolution'] in ('source-fallback','compiler-source-substitution') for row in rows for x in row['lookups'])

@pytest.mark.parametrize('case,code',[('reorder',0),('missing-always',1),('dynamic-key',2)])
def test_cli_exit_codes(case,code):
    s=next(s for s in MANIFEST if s['id']==case)
    done=subprocess.run([sys.executable,'-m','msgbranch.cli',str(ROOT/s['source']),str(ROOT/s['catalog']),'--max-count','2'],capture_output=True,text=True)
    assert done.returncode==code,done.stderr
    assert json.loads(done.stdout)

def test_fluent_executed_reference_scope_and_profile_restore():
    source='''-brand = { $case ->
    [formal] Company
   *[other] Brand
}
m = { -brand }
'''
    b=FluentBundle(['en'],use_isolating=False);b.add_resource(parse_bounded(source))
    assert sys.getprofile() is None
    with Trace() as t: actual,errors=b.format_pattern(b.get_message('m').value,{})
    assert sys.getprofile() is None
    assert actual=='Brand' and not errors
    assert t.result()['needed_external']==[]
    assert t.reads==[{'name':'case','present':False,'scope':'term-parameter','type':'missing'}]
    assert t.branches[0]['selection']=='default-fallthrough'
    assert t.branches[0]['selector']=={'fluent_none':'case'}  # Stable across process addresses.

def test_profile_restored_on_exception():
    with pytest.raises(RuntimeError):
        with Trace():raise RuntimeError('test cleanup')
    assert sys.getprofile() is None

def test_default_variant_can_match_without_fallback():
    s='''m = { $x ->
    [ready] Ready
   *[other] Other
}
'''
    b=FluentBundle(['en'],use_isolating=False);b.add_resource(parse_bounded(s))
    outcomes=[]
    for x in ['other','unknown']:
        with Trace() as t:b.format_pattern(b.get_message('m').value,{'x':x})
        outcomes.append(t.branches[0]['selection'])
    assert outcomes==['match','default-fallthrough']

def test_candidate_explicit_boundary_and_unknown_custom_function():
    s='''m = { CUSTOM($n) ->
    [301] Explicit
   *[other] Default
}
'''
    c=candidate_values(s,'m',5)
    assert 301 in c['values'] and c['unknown']==['custom/function selector: CUSTOM']

def test_native_parser_rejects_missing_default():
    with pytest.raises(ValueError):parse_bounded('m = { $n ->\n [one] One\n}\n')

def test_literal_call_recovery():
    rows=literal_calls('l.format_value("m", {"n": 1})\nl.format_value(key, args)\n')
    assert rows[0]['status']=='literal' and rows[0]['args']=={'n':1}
    assert rows[1]['status']=='unknown'

def test_pinned_runtime_contract_observations_not_fixed_by_adapter():
    # Regression on the observed snapshot, NOT assertions that these results are desired.
    s='''m = { $n ->
    [1] exact
   *[other] other
}
f = { NUMBER($n, minimumFractionDigits: 1) ->
    [one] one
   *[other] other
}
'''
    b=FluentBundle(['en'],use_isolating=False);b.add_resource(parse_bounded(s))
    assert b.format_pattern(b.get_message('m').value,{'n':Decimal('1')})==('other',[])
    assert b.format_pattern(b.get_message('f').value,{'n':1})==('one',[])
