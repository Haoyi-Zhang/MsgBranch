from pathlib import Path
import pytest
from msgbranch.project import audit_project, pattern_requirements, _qualification, Supplier

@pytest.mark.parametrize('mutation',[
    'args.clear()', 'del args["owner"]', 'args["owner"] = external()',
    'alias = args\n    alias.clear()', 'mutate(args)',
])
def test_unsupported_mutation_never_discharges_obligation(tmp_path: Path, mutation: str):
    source=tmp_path/'app.py'
    source.write_text('def render():\n    msg = gettext("%(owner)s")\n    args = {"owner": "Ada"}\n    '+mutation+'\n    return msg % args\n',encoding='utf-8')
    catalog=tmp_path/'messages.po'
    catalog.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n"Language: en\\n"\n\nmsgid "%(owner)s"\nmsgstr "%(owner)s"\n',encoding='utf-8')
    report=audit_project(source,[catalog],max_count=2)
    assert report['summary']['unknown']==1
    assert report['summary']['clean']==0

def test_known_use_does_not_hide_unresolved_use(tmp_path: Path):
    source=tmp_path/'app.py'
    source.write_text('def render():\n    msg = gettext("%(owner)s")\n    first = msg % {"owner": "Ada"}\n    second = msg % external()\n    return first, second\n',encoding='utf-8')
    catalog=tmp_path/'messages.po'
    catalog.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n"Language: en\\n"\n\nmsgid "%(owner)s"\nmsgstr "%(owner)s"\n',encoding='utf-8')
    assert audit_project(source,[catalog],max_count=2)['summary']['unknown']==1

@pytest.mark.parametrize('pattern,count,expected',[('{1}',1,'error'),('{0} {0}',1,'clean'),('{2}',3,'clean'),('{} {}',1,'error')])
def test_brace_position_requirements(pattern,count,expected):
    supplier=Supplier('known','str.format',positional=count,positional_types=('str',)*count)
    assert _qualification(pattern_requirements(pattern),supplier)['status']==expected

@pytest.mark.parametrize('pattern',['{x.missing}','{x[0]}','%*d','%.*f','{} {0}','{0:{1}}'])
def test_unmodeled_native_semantics_remain_unknown(pattern):
    assert pattern_requirements(pattern).status=='unknown'
