"""Execute the local study using the current Python interpreter on any platform."""
from pathlib import Path
import argparse, os, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    env=dict(os.environ)
    env['PYTHONPATH']=os.pathsep.join([str(ROOT/'src'),str(ROOT/'vendor/python-fluent')])
    env['PYTHONDONTWRITEBYTECODE']='1'
    subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'],
                   cwd=ROOT, env=env, check=True)
    print('unit tests: passed', flush=True)
    names=['verify_vendor','verify_inputs','make_controls','pilot','extraction_baseline',
           'evaluate','flow_validation','jupyter_boundary','fluent_evaluate','openhangar_boundary',
           'xrpl_boundary','azm_build_boundary','project_audit_evaluate','holdout_evaluate',
           'babel_cli_evaluate','project_scaling','bedrock_boundary']
    if args.full:
        names += ['partition_evaluate','partition_confirm','cost_evaluate']
    names += ['weblate_evaluate','localhero_evaluate','public_fix_screen','statistical_analysis',
              'reference_audit','availability','coverage_report','selector_reference','report',
              'verify_inputs','audit_results']
    for name in names:
        subprocess.run([sys.executable,str(ROOT/'scripts'/(name+'.py'))],cwd=ROOT,env=env,check=True)
        print(name+': passed',flush=True)

if __name__=='__main__':
    main()
