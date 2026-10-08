"""Regression for the explicit boundary of the predicate-coverage guarantee."""
from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
from msgbranch.partition import plan_partition
from msgbranch.program import Program
from msgbranch.runtime import CatalogRuntime


def test_external_obligation_boundary_needs_explicit_test(tmp_path):
    catalog = Catalog(locale='ja')
    catalog.add('status', 'regular')
    po = tmp_path / 'messages.po'
    with po.open('wb') as stream:
        write_po(stream, catalog)
    program = Program('def message(n):\n    return gettext("status")\n')
    runtime = CatalogRuntime(po)
    plan = plan_partition(program, runtime, high=200)
    assert not plan.unknown
    assert 37 not in plan.representatives

    # This acceptance condition is external to the program/catalog grammar.
    def obligation(n, result):
        return result.output == ('special' if n == 37 else 'regular')

    assert all(obligation(n, program.run(runtime, n)) for n in plan.representatives)
    assert not obligation(37, program.run(runtime, 37))
    # A successfully covered predicate vector is not a full-obligation proof.
