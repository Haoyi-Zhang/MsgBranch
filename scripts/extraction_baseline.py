"""Execute current Babel with archived Sphinx keyword configuration on source slices."""
from io import BytesIO
from pathlib import Path
import json
from babel.messages.extract import extract
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.runtime import CatalogRuntime
from msgbranch.baselines import lookup_kind_conflicts
ROOT=Path(__file__).resolve().parents[1]

def run():
    folder=ROOT/'data/upstream/sphinx'
    results=[]
    for revision in ['before','after']:
        source=(folder/f'{revision}.py').read_text()
        configurations={'historical_keyword_configuration':{'_':None,'__':None,'l_':None,'lazy_gettext':None},
                        'arity_aware_current_Babel':{'__':{1:None,3:(1,2)}}}
        for name,keywords in configurations.items():
            rows=list(extract('python',BytesIO(source.encode()),keywords=keywords))
            results.append({'revision':revision,'configuration':name,'extracted':rows})
        for locale in ['ja','de']:
            rt=CatalogRuntime(folder/f'{locale}.po')
            results.append({'revision':revision,'locale':locale,'configuration':'lookup-kind',
                            'conflicts':lookup_kind_conflicts(source,rt,overloaded_callees=('__',))})
    (ROOT/'results/extraction-baseline.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(results,indent=2,ensure_ascii=False))
    return results
if __name__=='__main__':run()
