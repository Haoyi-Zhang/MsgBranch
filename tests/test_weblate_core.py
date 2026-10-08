"""Regression vectors for the explicitly scoped Weblate-source excerpt harness.
These are independent fixture expectations, not Weblate's full upstream suite.
"""
from pathlib import Path
from types import SimpleNamespace
import pytest
from babel.messages.catalog import Catalog
from msgbranch.weblate_core import core,check_catalog

@pytest.mark.parametrize('source,target,alarm',[
 ('%(a)s %(b)s','%(b)s %(a)s',False),
 ('%(a)s','%(b)s',True),
 ('%(a)d','%(a)s',True),
 ('%(a)s %(a)s','%(a)s',True),
 ('%s %d','%d %s',True),
 ('%s %d','%s %d',False),
 ('100%% %(a)s','%(a)s 100%%',False),
 ('no tokens','no tokens',False),
 ('%(a)s','',False),
])
def test_percent_vectors(source,target,alarm):
    assert bool(core.PythonFormatCheck().check_format(source,target,False,None)) is alarm

@pytest.mark.parametrize('source,target,alarm',[
 ('{a} {b}','{b} {a}',False),
 ('{a}','{b}',True),
 ('{a:d}','{a:s}',True),
 ('{{ok}} {a}','{a} {{ok}}',False),
 ('{a}','{a} {',True),
 ('{} {}','{}',True),
])
def test_brace_vectors(source,target,alarm):
    assert bool(core.PythonBraceFormatCheck().check_format(source,target,False,None)) is alarm

def test_native_plural_example_singletons():
    e=core.plural_examples('(n != 1)')
    assert e[0]==['1'] and len(e[1])==11
    f=core.plural_examples('(n > 1)')
    assert f[0]==['0','1']

def test_flags_and_french_omission_policy():
    c=Catalog(locale='fr');c.add(('one day','%(n)s days'),('un jour','%(n)s jours'),flags=['python-format'])
    assert not check_catalog(c)[0]['alarm']
    assert check_catalog(c,strict=True)[0]['alarm']
    # Do not run a disabled check by pretending every string has format flags.
    c2=Catalog(locale='en');c2.add('literal','target')
    assert check_catalog(c2)==[]

def test_single_form_requires_plural_contract():
    c=Catalog(locale='ja');c.add(('one day','%(n)s days'),('days',),flags=['python-format'])
    assert check_catalog(c)[0]['alarm']
