"""Expose the source tree to CLI subprocesses during a direct pytest run."""
import os
from pathlib import Path
import pytest


@pytest.fixture(scope='session', autouse=True)
def source_tree_subprocess_path():
    root = Path(__file__).resolve().parents[1]
    previous = os.environ.get('PYTHONPATH')
    paths = [str(root / 'src'), str(root / 'vendor/python-fluent')]
    if previous:
        paths.append(previous)
    os.environ['PYTHONPATH'] = os.pathsep.join(paths)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('PYTHONPATH', None)
        else:
            os.environ['PYTHONPATH'] = previous
