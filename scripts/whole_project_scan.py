"""Parse all Python files in one pinned Solaar snapshot; never execute upstream code.

Acquire the official source archive separately. Both bounded modes receive every
Python file and the unchanged Danish catalog. Classifications remain conditional
on configured gettext bindings, not developer-adjudicated defects.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
import tarfile
import tempfile
import time

if __package__:
    from . import _repo_bootstrap
else:
    import _repo_bootstrap
from msgbranch.project import audit_project

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'data/whole-project/solaar-inputs.json'
MODES = ('direct', 'flow')
COUNT_BOUND = 200
METHOD_SECONDS = 180


def stamp():
    return datetime.now(timezone.utc).isoformat()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def safe_parts(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in ('..', '') for p in path.parts) or '\\' in name:
        raise ValueError('Unsafe archive name')
    return path.parts


def materialize(archive, destination, manifest):
    wanted = {item['path']: item for item in manifest['files']}
    if len(wanted) != len(manifest['files']) or sum(p.endswith('.py') for p in wanted) != 128:
        raise ValueError('Pinned manifest population mismatch')
    seen = set()
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        prefixes = {safe_parts(m.name)[0] for m in members}
        if len(prefixes) != 1:
            raise ValueError('Expected one upstream root')
        python_members = set()
        for member in members:
            parts = safe_parts(member.name)
            relative = '/'.join(parts[1:])
            if relative.endswith('.py'):
                python_members.add(relative)
            if relative not in wanted:
                continue
            if relative in seen or not member.isfile():
                raise ValueError('Duplicate or non-regular selected input')
            expected = wanted[relative]
            if member.size != expected['bytes']:
                raise ValueError('Selected input size mismatch: ' + relative)
            with source.extractfile(member) as handle:
                data = handle.read(expected['bytes'] + 1)
            if len(data) != expected['bytes'] or git_blob(data) != expected['git_blob']:
                raise ValueError('Selected input identity mismatch: ' + relative)
            target = destination.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            seen.add(relative)
        if seen != set(wanted) or python_members != {p for p in wanted if p.endswith('.py')}:
            raise ValueError('Archive does not match the complete pinned Python population')
    return len(seen)


def portable_report(report, source):
    """Normalize path fields only; never alter message/pattern/supplier text."""
    source = source.resolve()
    if Path(report['summary']['source_root']).resolve() != source:
        raise ValueError('Unexpected scanned source root')
    report['summary']['source_root'] = '<UPSTREAM_SOURCE>'
    for finding in report['findings']:
        if finding.get('catalog') is not None:
            catalog = Path(finding['catalog']).resolve()
            finding['catalog'] = '<UPSTREAM_SOURCE>/' + catalog.relative_to(source).as_posix()
        path = Path(finding['call']['path'])
        if path.is_absolute():
            path = path.resolve().relative_to(source)
        finding['call']['path'] = path.as_posix()
    return report


def worker(mode, source, output):
    started = stamp()
    begin = time.perf_counter()
    report = audit_project(source, [source / 'po/da.po'], max_count=COUNT_BOUND,
                           require_catalog=False, max_files=2000, analysis_mode=mode)
    elapsed = time.perf_counter() - begin
    if report['summary']['python_files'] != 128:
        raise ValueError('Not all pinned Python files were visited')
    report = portable_report(report, source)
    report['execution'] = {'started_at_utc': started, 'completed_at_utc': stamp(),
                           'elapsed_seconds': elapsed, 'wall_budget_seconds': METHOD_SECONDS,
                           'upstream_modules_imported_or_executed': False}
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def call_key(finding):
    call = finding['call']
    return call['path'], call['line'], call['column'], finding.get('catalog')


def summarize(report):
    reasons = Counter()
    for row in report['findings']:
        if row['status'] != 'unknown':
            continue
        values = {row.get('reason')} if row.get('reason') else set()
        for witness in row.get('witnesses', []):
            if witness['qualification']['status'] == 'unknown':
                values.add(witness['qualification'].get('reason') or 'unspecified qualification')
        for reason in values or {'unresolved qualification'}:
            reasons[reason] += 1
    return {'summary': report['summary'], 'execution': report['execution'],
            'unknown_reason_counts_nonexclusive': dict(sorted(reasons.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-archive', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/whole-project.json.gz')
    parser.add_argument('--worker', choices=MODES)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.source, args.output)
        return
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'results').resolve()) or output.exists():
        raise ValueError('Use a new output under artifact/results')
    if not args.source_archive or not args.source_archive.is_file():
        raise ValueError('Supply the official pinned source archive')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    sources = [*sorted((ROOT / 'src/msgbranch').glob('*.py')),
               Path(__file__).resolve(), ROOT / 'scripts/_repo_bootstrap.py', MANIFEST]
    bindings = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    reports = {}
    with tempfile.TemporaryDirectory(prefix='msgbranch-static-inputs-') as temporary:
        work = Path(temporary)
        source = work / 'source'
        source.mkdir()
        files_bound = materialize(args.source_archive, source, manifest)
        for mode in MODES:
            result = work / (mode + '.json')
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', mode,
                            '--source', str(source), '--output', str(result)],
                           check=True, timeout=METHOD_SECONDS)
            reports[mode] = json.loads(result.read_text(encoding='utf-8'))
    if bindings != {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise ValueError('Measured source changed')
    identities = [{call_key(row) for row in reports[mode]['findings']} for mode in MODES]
    transitions = Counter()
    if identities[0] == identities[1]:
        direct = {call_key(row): row['status'] for row in reports['direct']['findings']}
        for row in reports['flow']['findings']:
            transitions[direct[call_key(row)] + '_to_' + row['status']] += 1
    record = {'input': manifest, 'inputs_bound': files_bound, 'source_bindings': bindings,
              'configuration': {'modes': list(MODES), 'count_domain': [0, COUNT_BOUND],
                                'require_catalog': False, 'source_modules_executed': False,
                                'singular_callees': ['gettext', '_'], 'plural_callees': ['ngettext'],
                                'contextual_callees': ['pgettext', 'npgettext']},
              'environment': {'python': sys.version, 'platform': platform.platform(),
                              'Babel': importlib.metadata.version('Babel')},
              'scope': 'Complete pinned repository Python-file scan, one Danish catalog, configured wrappers. Conditional analyzer classifications, not manual defect adjudication, full-application execution, recall, deployment or adoption.',
              'reports': reports}
    summary = {k: record[k] for k in ('inputs_bound', 'source_bindings', 'configuration', 'environment', 'scope')}
    summary.update({'repository': manifest['repository'], 'commit': manifest['commit'],
                    'same_finding_identities': identities[0] == identities[1],
                    'classification_transitions': dict(sorted(transitions.items())),
                    'methods': {m: summarize(reports[m]) for m in MODES}})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0))
    summary_path = output.with_name(output.name.removesuffix('.json.gz') + '-summary.json')
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
