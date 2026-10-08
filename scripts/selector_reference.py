"""Optional independent category check, not another Fluent evaluator.

Declared after the exploratory Fluent probes. Node's Intl implementation
corroborates only the English fraction-digit expectation for numeric 1.
"""
from pathlib import Path
import json, shutil, subprocess
ROOT=Path(__file__).resolve().parents[1]
def run():
    node=shutil.which('node')
    if not node:
        result={'status':'unavailable','reason':'Node.js not installed','scope':'optional oracle corroboration only'}
    else:
        code='''const plain = new Intl.PluralRules("en");
const fixed = new Intl.PluralRules("en", {minimumFractionDigits: 1});
const result = {status:"executed", versions:process.versions,
 plain_one:plain.select(1), fixed_one:fixed.select(1), fixed_float_one:fixed.select(1.0),
 options:fixed.resolvedOptions(), scope:"category expectation only; not Fluent runtime parity"};
if (result.plain_one !== "one" || result.fixed_one !== "other") process.exit(1);
console.log(JSON.stringify(result));'''
        result=json.loads(subprocess.check_output([node,'-e',code],text=True,timeout=10))
    (ROOT/'results/selector-reference.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':run()
