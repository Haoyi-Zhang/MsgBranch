import ast
from pathlib import Path
import json
import gettext
import pytest
from msgbranch.partition import GuardPartition, plan_partition
from msgbranch.program import Program, Unsupported, representatives, signature
from msgbranch.runtime import CatalogRuntime

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('expr', ['n == 173','n != 173','n <= 173','n >= 173','173 < n',
                                 'n%7 == 3','n%10 == 1 and n%100 != 11',
                                 '172 <= n < 179','not(n < 31 or n > 173)',
                                 'n%3 == 1 or n == 41','n','n%5'])
def test_predicates_constant_within_cells(expr):
    p=GuardPartition(0,1000)
    node=ast.parse(expr,mode='eval').body
    p.add_predicate(node)
    cells=p.cells()
    # Trusted hardcoded expressions; independent Python semantics, not a parser
    # roundtrip through the construction under test.
    pred=compile(ast.Expression(node),'test-predicate','eval')
    covered=set()
    for c in cells:
        want=bool(eval(pred, {'__builtins__':{}}, {'n':c.witness}))
        for n in range(c.low,c.high+1):
            if n%c.modulus==c.residue:
                assert bool(eval(pred, {'__builtins__':{}}, {'n':n})) == want
                assert n not in covered
                covered.add(n)
    assert covered==set(range(1001))

@pytest.mark.parametrize('formula',['0','n!=1','n>1',
  'n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<12 || n%100>14) ? 1 : 2',
  'n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5'])
def test_native_plural_value_constant(formula):
    p=GuardPartition(0,1000); p.add_plural_formula(formula)
    f=gettext.c2py(formula)
    for c in p.cells():
        for n in range(c.witness,c.high+1,c.modulus):
            assert f(n)==f(c.witness)

@pytest.mark.parametrize('expr',['n//10 == 1','n%0==0','n%k==0','x==4','n+1 == 4','n==n%10','n in [1,2]'])
def test_unsupported_guard_fails_closed(expr):
    with pytest.raises(Unsupported):GuardPartition().add_predicate(ast.parse(expr,mode='eval').body)

@pytest.mark.parametrize('formula',['n','n/10','n%10','n%0==1','n ? n : 0'])
def test_unsupported_formula_fails_closed(formula):
    with pytest.raises(Unsupported):GuardPartition().add_plural_formula(formula)

def test_budget_and_count_reassignment():
    p=GuardPartition(max_cells=8)
    with pytest.raises(Unsupported):p.add_predicate(ast.parse('n%97==1',mode='eval').body)
    p=GuardPartition(max_cells=2);p.add_predicate(ast.parse('n==7',mode='eval').body)
    with pytest.raises(Unsupported):p.cells()
    with pytest.raises(Unsupported):GuardPartition().add_program(Program('def message(n):\n n=3\n return gettext("hi")'))

def test_arithmetic_rejected():
    with pytest.raises(Unsupported):
        GuardPartition().add_program(Program('def message(n):\n a = n + 999999999999\n return gettext("%d") % a'))

def test_all_existing_supported_controls_match_exhaustive():
    for c in json.loads((ROOT/'data/control-manifest.json').read_text()):
        if c['category']=='unknown':continue
        p=Program((ROOT/c['source']).read_text());r=CatalogRuntime(ROOT/c['catalog'])
        new=plan_partition(p,r)
        old,_=representatives(p,r,list(range(201)))
        assert new.representatives==old,c['id']

def test_source_fallback_boundary_with_single_form():
    p=Program((ROOT/'data/controls/intended-fallback/call.py').read_text())
    r=CatalogRuntime(ROOT/'data/controls/japanese-one-form/messages.po')
    result=plan_partition(p,r)
    assert 1 in result.cuts and 2 in result.cuts

@pytest.mark.parametrize('source',[
 'def message(n):\n return gettext("%(x)s") % {str(n): n}',
 'def message(n):\n v = (n == 173 and "bad") or n\n return gettext("%d") % v',
 'def message(n):\n return gettext("%(x)d") % {"x": n == 173}',
])
def test_unmodelled_argument_shape_changes_rejected(source):
    with pytest.raises(Unsupported):GuardPartition().add_program(Program(source))

def test_nonstring_result_remains_unknown_during_planning():
    p=Program('def message(n):\n return n')
    rt=CatalogRuntime(ROOT/'data/controls/japanese-one-form/messages.po')
    assert p.run(rt,2,plan=True).status=='unknown'
    assert p.run(rt,2).status=='unknown'
    assert plan_partition(p,rt).unknown

def test_cell_coalescing_charged_separately():
    rt=CatalogRuntime(ROOT/'data/validation/ru-0/messages.po')
    p=Program((ROOT/'data/validation/ru-0/mutant.py').read_text())
    result=plan_partition(p,rt,high=1000)
    assert result.planning_calls < result.cell_evaluations
    assert len(result.coalesced_witnesses)==result.planning_calls
    old,_=representatives(p,rt,list(range(1001)))
    assert result.representatives==old
