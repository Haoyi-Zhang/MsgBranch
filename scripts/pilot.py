"""Execute the source-extracted Sphinx localization boundary; no Sphinx build."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.runtime import CatalogRuntime
ROOT = Path(__file__).resolve().parents[1]

def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run():
    folder = ROOT/'data/upstream/sphinx'
    boundary = load(folder/'locale_boundary.py')
    results=[]
    for locale in ['ja','de']:
        rt = CatalogRuntime(folder/f'{locale}.po')
        # Inject real tracked GNUTranslations into upstream registered wrapper.
        boundary.translators[('console','sphinx')] = rt
        translate = boundary.get_translation('sphinx', 'console')
        for version in ['before','after']:
            app=load(folder/f'{version}.py')
            for n in [0,1,2,11,21,100]:
                rt.reset()
                state=SimpleNamespace(statuscode=0, warningiserror=False, _warncount=n)
                output=app.build_message(state,translate)
                # Only n=1, Japanese, has the observed translated form and repair oracle.
                expected='ビルド 成功, 1 warning.' if locale=='ja' and n==1 else None
                results.append({'locale':locale,'revision':version,'n':n,'output':output,
                    'expected':expected,'oracle_failure': expected is not None and output!=expected,
                    'catalog_checks':rt.checks,'trace':rt.serialize_trace()})
    out=ROOT/'results/pilot.json'
    out.write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'executions':len(results),'repair_oracle_failures':sum(r['oracle_failure'] for r in results),
       'before_n1':results[1]['output'],'after_n1':results[7]['output'],
       'babel_errors':sum(len(r['catalog_checks']) for r in results)},ensure_ascii=False,indent=2))
    assert results[1]['oracle_failure'] and not results[7]['oracle_failure']
    assert not any(r['catalog_checks'] for r in results)
    return results
if __name__=='__main__': run()
