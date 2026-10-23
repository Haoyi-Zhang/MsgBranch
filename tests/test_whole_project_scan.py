"""Owned archive/path fixtures; no network or upstream program execution."""
from io import BytesIO
from pathlib import Path
import gzip
import json
import tarfile
import pytest
from scripts import whole_project_scan as scan
from scripts import whole_project_receipt as receipt


def archive_fixture(tmp_path, defect=None):
    files = {f'lib/case{i}.py': b'# Owned inert fixture\n' for i in range(128)}
    files.update({'po/da.po': b'# Owned catalog fixture\n', 'LICENSE.txt': b'Owned fixture\n'})
    manifest = {'files': [{'path': name, 'bytes': len(data), 'git_blob': scan.git_blob(data)}
                          for name, data in files.items()]}
    archive = tmp_path / 'input.tar.gz'
    with tarfile.open(archive, 'w:gz') as out:
        for index, (name, data) in enumerate(files.items()):
            if index == 0 and defect == 'missing':
                continue
            item = tarfile.TarInfo('source/' + name)
            item.size = len(data)
            if index == 0 and defect == 'link':
                item.type = tarfile.SYMTYPE
                item.linkname = 'elsewhere'
                item.size = 0
            out.addfile(item, BytesIO(data) if item.isfile() else None)
        if defect == 'extra_python':
            item = tarfile.TarInfo('source/extra.py')
            item.size = 1
            out.addfile(item, BytesIO(b'x'))
        if defect == 'unsafe':
            item = tarfile.TarInfo('source/../escape.py')
            item.size = 1
            out.addfile(item, BytesIO(b'x'))
    if defect == 'wrong_identity':
        manifest['files'][0]['git_blob'] = '0' * 40
    return archive, manifest


def test_complete_selected_population_is_verified(tmp_path):
    archive, manifest = archive_fixture(tmp_path)
    assert scan.materialize(archive, tmp_path / 'selected', manifest) == 130
    assert len(list((tmp_path / 'selected').rglob('*.py'))) == 128


@pytest.mark.parametrize('defect', ['missing', 'link', 'extra_python', 'unsafe', 'wrong_identity'])
def test_untrusted_archive_changes_are_rejected(tmp_path, defect):
    archive, manifest = archive_fixture(tmp_path, defect)
    with pytest.raises(ValueError):
        scan.materialize(archive, tmp_path / 'selected', manifest)


def test_path_normalization_does_not_rewrite_scientific_strings(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    text = r'This message has \\n and \\t and C:\\literal'
    report = {'summary': {'source_root': str(source)},
              'findings': [{'call': {'path': 'lib/source.py', 'singular': text},
                            'catalog': str(source / 'po/da.po'),
                            'witnesses': [{'pattern': text, 'output': text}]}]}
    actual = scan.portable_report(report, source)
    assert actual['summary']['source_root'] == '<UPSTREAM_SOURCE>'
    finding = actual['findings'][0]
    assert finding['catalog'] == '<UPSTREAM_SOURCE>/po/da.po'
    assert finding['call']['singular'] == text
    assert finding['witnesses'][0] == {'pattern': text, 'output': text}


def test_catalog_outside_verified_source_is_rejected(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    report = {'summary': {'source_root': str(source)},
              'findings': [{'call': {'path': 'source.py'}, 'catalog': str(tmp_path / 'outside.po')}]}
    with pytest.raises(ValueError):
        scan.portable_report(report, source)


def test_selected_scientific_receipt_is_current_and_complete():
    checked = receipt.read_current()
    assert checked['python_files'] == 128
    assert checked['findings_per_mode'] == 698
    assert checked['methods']['flow']['unknown'] == 402


@pytest.mark.parametrize('defect', ['count', 'raw_status', 'source', 'configuration',
                                  'missing_finding', 'witness_count', 'input_population'])
def test_receipt_consumer_rejects_drift(defect):
    data = json.loads(gzip.decompress((scan.ROOT / 'results/whole-project.json.gz').read_bytes()))
    if defect == 'count':
        data['reports']['flow']['summary']['unknown'] -= 1
    elif defect == 'raw_status':
        data['reports']['flow']['findings'][0]['status'] = 'invalid-status'
    elif defect == 'source':
        data['source_bindings']['src/msgbranch/project.py'] = '0' * 64
    elif defect == 'configuration':
        data['configuration']['count_domain'] = [0, 199]
    elif defect == 'missing_finding':
        data['reports']['flow']['findings'].pop()
    elif defect == 'witness_count':
        data['reports']['flow']['summary']['selected_patterns'] += 1
    elif defect == 'input_population':
        data['inputs_bound'] -= 1
    with pytest.raises(ValueError):
        receipt.validate(data)
