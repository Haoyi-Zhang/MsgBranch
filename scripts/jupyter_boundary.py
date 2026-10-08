"""Replay a real application method with local doubles, never launch a server."""
from pathlib import Path
from types import SimpleNamespace
import typing
import json
import importlib.util
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.runtime import CatalogRuntime
ROOT=Path(__file__).resolve().parents[1]

def state(n):
    return SimpleNamespace(contents_manager=SimpleNamespace(info_string=lambda:'LOCAL TEST DIRECTORY'),
        kernel_manager=SimpleNamespace(list_kernel_ids=lambda:list(range(n))),
        display_url='LOCAL TEST ENDPOINT (NOT OPENED)',
        gateway_config=SimpleNamespace(gateway_enabled=False))

def run():
    folder=ROOT/'data/upstream/jupyter'
    rt=CatalogRuntime(folder/'notebook.po')
    scope={'t':typing,'trans':rt,'_i18n':rt.gettext,'ServerApp':SimpleNamespace(version='2.17.0')}
    # Trusted exact upstream slice, not the public CLI's input path.
    exec(compile((folder/'running_server_info.py').read_text(),'running_server_info.py','exec'),scope)
    rows=[]
    for n in range(201):
        rt.reset()
        result=scope['running_server_info'](state(n))
        expected=f'{n} 活跃的服务'
        assert result.splitlines()[1]==expected
        rows.append({'n':n,'output':result,'expected_count_line':expected,'trace':rt.serialize_trace(),
                     'oracle_failure':result.splitlines()[1]!=expected})
    native=[]
    try:
        import jupyter_server.serverapp as app
        from importlib.metadata import version
        if version('jupyter_server')!='2.17.0':
            native=[{'status':'unavailable','reason':'native package version differs from 2.17.0'}]
        else:
            saved=app.trans,app._i18n
            try:
                app.trans,app._i18n=rt,rt.gettext
                for n in [0,1,2,100]:
                    result=app.ServerApp.running_server_info(state(n))
                    assert result==rows[n]['output']
                    native.append({'n':n,'status':'match','output':result})
            finally:
                app.trans,app._i18n=saved
    except ImportError:
        native=[{'status':'unavailable','reason':'optional native package is not installed'}]
    summary={'boundary_runs':len(rows),'native_method_comparisons':native,
             'validated_defects':0,'full_catalog_babel_checks':rt.checks,
             'count_branches':sorted({r['trace'][0]['branch'] for r in rows}),
             'binding':'explicit injected compiled catalog; not application locale discovery',
             'split':'additional discovery/transfer control; not held out'}
    (ROOT/'results/jupyter-runs.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n')
    (ROOT/'results/jupyter-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    return rows,summary
if __name__=='__main__':run()
