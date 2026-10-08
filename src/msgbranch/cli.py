"""Command-line interface; never imports or executes the supplied Python file."""
import argparse
import json
from pathlib import Path
from .program import Program, Unsupported, representatives
from .runtime import CatalogRuntime
from .partition import plan_partition

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('--planner', choices=['exhaustive', 'partition'], default='exhaustive')
    parser.add_argument('--function', default='message')
    parser.add_argument('--max-count', type=int, default=200)
    parser.add_argument('--require-catalog', action='store_true', help='Explicit application obligation: source fallback is not permitted')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 0 <= args.max_count <= 10000:
        parser.error('--max-count must be 0..10000')
    try:
        program = Program(args.source.read_text(encoding='utf-8'), args.function)
        rt = CatalogRuntime(args.catalog)
        plan = None
        if args.planner == 'partition':
            plan = plan_partition(program, rt, high=args.max_count)
            selected, unknown = plan.representatives, plan.unknown
        else:
            selected, unknown = representatives(program, rt, list(range(args.max_count + 1)))
        results = [program.run(rt, n).to_dict() for n in selected]
        # Execution may reject a value that planning could not classify.
        # Such a result must not become a successful command-line exit.
        for result in results:
            if result['status'] == 'unknown' and not any(u['n'] == result['n'] for u in unknown):
                unknown.append({'n': result['n'], 'reason': result['error']})
        fallback = args.require_catalog and any(x['resolution'] in ('source-fallback', 'compiler-source-substitution') for r in results for x in r['lookups'])
        report = {'planner': args.planner, 'partition': plan.to_dict() if plan else None, 'domain': [0,args.max_count], 'representatives': selected, 'unknown': unknown,
                  'babel_checks': rt.checks, 'results': results, 'fallback_obligation_violated': bool(fallback),
                  'claim': 'bounded witnesses only; unsupported paths are unknown; no linguistic correctness judgement'}
        code = 2 if unknown else (1 if fallback or any(r['status']=='error' for r in results) else 0)
    except (Unsupported, OSError, ValueError, SyntaxError) as exc:
        report, code = {'status':'unavailable-or-unknown','error':str(exc)}, 2
    text = json.dumps(report, ensure_ascii=False, indent=2)+'\n'
    if args.output:
        args.output.write_text(text,encoding='utf-8')
    else:
        print(text,end='')
    raise SystemExit(code)

if __name__ == '__main__':
    main()
