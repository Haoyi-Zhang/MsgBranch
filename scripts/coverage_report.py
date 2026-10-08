"""Compute finite-domain reachable branch units, not language completeness."""
from pathlib import Path
from collections import defaultdict
import json, csv
ROOT=Path(__file__).resolve().parents[1]

def load_jsonl(path: Path):
    """Read JSON Lines by physical LF records, not Unicode splitlines.

    A valid JSON string may contain U+0085 (NEL), for example when a trusted
    ``%c`` control formats the integer 133.  ``str.splitlines()`` treats NEL as
    a record boundary even though the JSONL file does not, producing a false
    truncated-record failure.  Text iteration follows the file's actual newline
    delimiters and preserves that character inside the JSON string.
    """
    with path.open(encoding='utf-8', newline='') as stream:
        return [json.loads(line) for line in stream if line.strip()]

def run():
    out=ROOT/'results'
    summaries=json.loads((out/'controls.json').read_text())
    raw=load_jsonl(out/'control-runs.jsonl')
    groups=defaultdict(list)
    for r in raw: groups[r['case']].append(r)
    rows=[]
    for c in summaries:
        if c['category']=='unknown': continue
        def units(r):
            return {(z['method'],z['singular'],z['branch'],z['resolution']) for z in r['lookups']}
        full=set().union(*(units(r) for r in groups[c['id']]))
        ordinary=set().union(*(units(r) for r in groups[c['id']] if r['n'] in c['ordinary']))
        selected=set().union(*(units(r) for r in groups[c['id']] if r['n'] in c['representatives']))
        rows.append(dict(format='gettext',case=c['id'],reachable=len(full),ordinary=len(ordinary),selected=len(selected)))
    groups=defaultdict(list)
    for r in json.loads((out/'fluent-runs.json').read_text()):groups[r['case']].append(r)
    for name,rs in groups.items():
        if rs[0]['category']=='runtime-contract-probe':continue
        # The first case with each trace/type signature is the same retained
        # observation selected in fluent_evaluate.py. JSON keeps input_type
        # for int/float/Decimal, and contract probes are not in this coverage.
        def units(r):
            return {(b['span'],b['variant']) for b in r['trace']['branches']}
        chosen={}
        for r in rs:
            # Strip selector values: they do not identify a branch location.
            bs=tuple((b['span'],b['variant'],b['selection']) for b in r['trace']['branches'])
            reads=tuple((x['name'],x['present'],x['scope'],x['type']) for x in r['trace']['reads'])
            chosen.setdefault((bs,reads),r)
        full=set().union(*(units(r) for r in rs))
        ordinary=set().union(*(units(r) for r in rs if r['input_type']=='int' and r['input'] in [1,2]))
        selected=set().union(*(units(r) for r in chosen.values()))
        rows.append(dict(format='Fluent',case=name,reachable=len(full),ordinary=len(ordinary),selected=len(selected)))
    with (out/'branch-coverage.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['format','case','reachable','ordinary','selected']);w.writeheader();w.writerows(rows)
    totals={form:{k:sum(r[k] for r in rows if r['format']==form) for k in ['reachable','ordinary','selected']} for form in ['gettext','Fluent']}
    result={'unit':'case-local lookup identity/index/resolution for gettext; case-local selector source span plus selected variant for Fluent',
            'denominator':'units observed in the full declared input domain; unknown gettext families and exploratory Fluent contract probes excluded; branchless cases contribute zero Fluent selector units',
            'totals':totals,'selection':'Fluent selected coverage is derived from post-execution trace grouping; not predictive reachability or reduced planning cost'}
    (out/'branch-coverage.json').write_text(json.dumps(result,indent=2)+'\n')
    paper=ROOT.parent/'paper'
    if paper.is_dir():
        text=r'\begin{tabular}{@{}lrrr@{}}'+ '\n'+r'\toprule Format & Reachable & Ordinary & Retained \\ \midrule'+'\n'
        for form in ['gettext','Fluent']:
            text+=form+' & '+' & '.join(str(totals[form][k]) for k in ['reachable','ordinary','selected'])+r' \\'+'\n'
        text+=r'\bottomrule \end{tabular}'+'\n'
        (paper/'generated/branch-coverage.tex').write_text(text)
    print(json.dumps(result,indent=2))
if __name__=='__main__':run()
