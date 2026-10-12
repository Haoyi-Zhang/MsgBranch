"""Owned PO/caller controls for native percent escapes."""
from io import BytesIO

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
import pytest

from msgbranch.project import audit_project
from msgbranch.runtime import CatalogRuntime


def _observe(tmp_path, pattern, mode):
    app=tmp_path/'caller.py'
    app.write_text(f'def render():\n    return gettext({pattern!r}) % {{"x": "Ada"}}\n',encoding='utf-8')
    catalog=Catalog(locale='en')
    catalog.add(pattern,pattern)
    buffer=BytesIO()
    write_po(buffer,catalog)
    po=tmp_path/'messages.po'
    po.write_bytes(buffer.getvalue())
    report=audit_project(app,[po],max_count=2,analysis_mode=mode)
    assert report['summary']['findings']==1
    native=CatalogRuntime(po).translator.gettext(pattern)
    return native,report['findings'][0]


@pytest.mark.parametrize('mode',['direct','flow'])
@pytest.mark.parametrize('pattern',['%3%','%-3%','%#%','%0%','%.2%','%l%','%(x)%','%+%'])
def test_decorated_percent_escape_is_not_clean(tmp_path,mode,pattern):
    native,finding=_observe(tmp_path,pattern,mode)
    with pytest.raises(ValueError):
        native % {'x':'Ada'}
    assert finding['status']=='unknown'
    assert finding['witnesses'][0]['qualification']['reason']=='literal percent escape must be doubled without decorations'


@pytest.mark.parametrize('mode',['direct','flow'])
@pytest.mark.parametrize('pattern',['%%','rate: 100%%','%% %(x)s','%(x)s %%','%%%%'])
def test_exact_percent_escapes_and_value_directives_remain_clean(tmp_path,mode,pattern):
    native,finding=_observe(tmp_path,pattern,mode)
    assert isinstance(native % {'x':'Ada'},str)
    assert finding['status']=='clean'
