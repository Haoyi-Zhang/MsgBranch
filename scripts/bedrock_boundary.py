from pathlib import Path
import importlib.util,json,hashlib
if __package__:
    from . import _repo_bootstrap  # noqa: F401
else:
    import _repo_bootstrap  # noqa: F401

from msgbranch.fluent_adapter import Trace
R=Path(__file__).resolve().parents[1];D=R/'data/bedrock'
spec=importlib.util.spec_from_file_location('bedrock_boundary',D/'boundary.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
CASES=[
(['de','en'],'fluent-title',{},'Title in German'),
(['de','en'],'fluent-page-desc',{'lang':'Dudeish'},'Description in Dudeish'),
(['de','en'],'brand-new-string',{},'New string not yet available in all languages'),
(['de','en'],'brand-new-string',{'fallback':'fluent-title'},'Title in German'),
(['en-US','en'],'fluent-brand',{},'English Fluent'),
(['de','en'],'fluent-brand',{},'German Fluent'),
(['fr','en'],'fluent-brand',{},'French Couramment')]
def run():
    prov=json.loads((D/'PROVENANCE.json').read_text())
    for item in prov['upstream_files']:
        raw=(D/item['local']).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==item['git_blob_sha1']
    rows=[]
    for locales,key,kwargs,expected in CASES:
        direct=b.translate(b.get_l10n(locales),key,**kwargs)
        with Trace() as trace:
            observed=b.translate(b.get_l10n(locales),key,**kwargs)
        data=trace.result()
        assert observed==direct==expected,(key,direct,expected)
        assert not any(x['errors'] for x in data['formats'])
        rows.append({'locales':locales,'message_id':key,'kwargs':kwargs,'expected':expected,'direct':direct,'observed':observed,'trace':data})
    summary={'upstream_assertions':len(rows),'native_executions':2*len(rows),'disagreements':0,'format_error_alarms':0,'byte_verified_upstream_files':len(prov['upstream_files']),'scope':prov['scope']}
    (R/'results/bedrock-runs.json').write_text(json.dumps(rows,indent=2)+'\n')
    (R/'results/bedrock-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2));return summary
if __name__=='__main__':run()
