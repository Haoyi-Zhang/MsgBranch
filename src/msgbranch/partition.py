"""Predictive integer guard partitions; native gettext still selects messages.

A cell is an interval and a residue modulo the LCM of literal moduli. We only
admit Boolean combinations of n-versus-integer and n%literal-versus-integer
comparisons. The partition preserves these predicates, not arbitrary rendered
values. Unsupported expressions and resource limits fail closed. This module
never executes input source or evaluates the translated formula with eval().
"""
from __future__ import annotations
import ast
from dataclasses import asdict, dataclass
import gettext
import operator
from math import lcm
from typing import Iterable
from .program import Program, Unsupported, signature
from .runtime import CatalogRuntime


@dataclass(frozen=True)
class Cell:
    low: int
    high: int
    modulus: int
    residue: int
    witness: int


@dataclass
class PartitionPlan:
    domain: tuple[int, int]
    period: int
    cuts: list[int]
    cells: list[Cell]
    representatives: list[int]
    unknown: list[dict]
    planning_calls: int
    cell_evaluations: int
    coalesced_witnesses: list[int]
    guarantee: str = 'admitted predicate-vector coverage; not arbitrary output equivalence'

    def to_dict(self):
        return asdict(self)


class GuardPartition:
    """Conservative, independently testable predicate partition builder."""
    def __init__(self, low: int = 0, high: int = 10000, *, max_cells: int = 20000):
        if type(low) is not int or type(high) is not int or not 0 <= low <= high <= 10000:
            raise ValueError('integer domain must be a nonempty interval within 0..10000')
        if type(max_cells) is not int or max_cells < 1:
            raise ValueError('max_cells must be a positive integer')
        self.low, self.high, self.max_cells = low, high, max_cells
        self.cuts = {low, high + 1}
        self.period = 1
        self.source_predicates: list[ast.AST] = []

    @staticmethod
    def integer(node: ast.AST) -> int | None:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = GuardPartition.integer(node.operand)
            if value is not None:
                return -value if isinstance(node.op, ast.USub) else value
        return None

    def operand(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name) and node.id == 'n':
            return 'n'
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Name) and node.left.id == 'n'):
            modulus = self.integer(node.right)
            if modulus is None or not 1 <= modulus <= 10000:
                raise Unsupported('partition: modulus must be a positive literal <=10000')
            self.period = lcm(self.period, modulus)
            if self.period > self.max_cells:
                raise Unsupported('partition: residue-period budget')
            return 'residue'
        if self.integer(node) is not None:
            return 'constant'
        raise Unsupported('partition: nonliteral or arithmetic guard operand')

    def add_comparison(self, left: ast.AST, operator: ast.AST, right: ast.AST):
        if not isinstance(operator, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            raise Unsupported('partition: guard comparison operator')
        a, b = self.operand(left), self.operand(right)
        if a != 'constant' and b != 'constant':
            raise Unsupported('partition: one guard operand must be an integer literal')
        if 'n' in (a, b):
            threshold = self.integer(left if a == 'constant' else right)
            assert threshold is not None
            # Both cuts cover all six comparison operators, including an isolated
            # equality point. Redundant cuts are harmless and deterministic.
            self.cuts.update(k for k in (threshold, threshold + 1)
                             if self.low < k <= self.high)

    def add_predicate(self, node: ast.AST):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for child in node.values:
                self.add_predicate(child)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self.add_predicate(node.operand)
        elif isinstance(node, ast.Compare):
            for left, op, right in zip([node.left] + node.comparators, node.ops, node.comparators):
                self.add_comparison(left, op, right)
        elif isinstance(node, ast.Constant) and type(node.value) in (int, bool):
            return
        elif isinstance(node, ast.Name) and node.id == 'n':
            self.add_comparison(node, ast.NotEq(), ast.Constant(0))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            self.add_comparison(node, ast.NotEq(), ast.Constant(0))
        else:
            raise Unsupported(f'partition: unsupported predicate {type(node).__name__}')

    def add_plural_formula(self, formula: str):
        if not isinstance(formula, str) or not formula or len(formula) > 1000:
            raise Unsupported('partition: plural formula size')
        try:
            converted, rest = gettext._parse(gettext._tokenize(formula), 0)
            if rest:
                raise Unsupported('partition: unconsumed plural formula')
            root = ast.parse(converted, mode='eval').body
        except (ValueError, SyntaxError, RecursionError) as exc:
            raise Unsupported('partition: plural formula parser rejected input') from exc

        def visit(node):
            if isinstance(node, ast.IfExp):
                self.add_predicate(node.test)
                visit(node.body)
                visit(node.orelse)
            elif self.integer(node) is not None:
                return
            elif isinstance(node, (ast.Compare, ast.BoolOp, ast.UnaryOp)):
                self.add_predicate(node)
            else:
                # A formula such as plural=n changes on every integer and is not
                # a piecewise-constant selector in the admitted grammar.
                raise Unsupported('partition: nonconstant plural leaf')
        visit(root)

    def add_program(self, program: Program):
        # Arithmetic value transformations can cross interpreter budgets or
        # conversion-error boundaries that are absent from the guard model.
        # Reject them rather than promoting predicate coverage to program safety.
        guard_nodes = {id(child) for top in ast.walk(program.function)
                       if isinstance(top, (ast.If, ast.IfExp))
                       for child in ast.walk(top.test)}
        message_names = {node.targets[0].id for node in ast.walk(program.function)
                         if isinstance(node, ast.Assign) and len(node.targets) == 1
                         and isinstance(node.targets[0], ast.Name)
                         and isinstance(node.value, ast.Call)
                         and isinstance(node.value.func, ast.Name)
                         and node.value.func.id in ('gettext', '_', 'ngettext', 'pgettext', 'npgettext')}
        for node in ast.walk(program.function):
            if isinstance(node, ast.Dict) and any(not isinstance(k, ast.Constant) or not isinstance(k.value, str) for k in node.keys):
                raise Unsupported('partition: mapping keys must be literal strings')
            if id(node) not in guard_nodes and (isinstance(node, (ast.BoolOp, ast.Compare)) or (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not))):
                raise Unsupported('partition: predicate-valued data requires exhaustive planning')
            if isinstance(node, ast.BinOp) and id(node) not in guard_nodes:
                left = node.left
                is_message = ((isinstance(left, ast.Name) and left.id in message_names)
                              or (isinstance(left, ast.Call) and isinstance(left.func, ast.Name)
                                  and left.func.id in ('gettext', '_', 'ngettext', 'pgettext', 'npgettext')))
                if not (isinstance(node.op, ast.Mod) and is_message):
                    raise Unsupported('partition: value arithmetic requires exhaustive planning')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'int':
                if len(node.args) != 1 or not (isinstance(node.args[0], ast.Constant)
                                              or (isinstance(node.args[0], ast.Name) and node.args[0].id == 'n')):
                    raise Unsupported('partition: value-sensitive int conversion')
        for node in ast.walk(program.function):
            if isinstance(node, (ast.If, ast.IfExp)):
                self.add_predicate(node.test)
                self.source_predicates.append(node.test)
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == 'n' for t in node.targets):
                    raise Unsupported('partition: reassigned count')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ('ngettext', 'npgettext'):
                    expected = 3 if node.func.id == 'ngettext' else 4
                    count_index = 2 if node.func.id == 'ngettext' else 3
                    if len(node.args) != expected or node.keywords:
                        raise Unsupported('partition: translation arity')
                    count = node.args[count_index]
                    if not ((isinstance(count, ast.Name) and count.id == 'n')
                            or self.integer(count) is not None):
                        raise Unsupported('partition: transformed or dynamic lookup count')
                elif node.func.id == 'pgettext':
                    if len(node.args) != 2 or node.keywords:
                        raise Unsupported('partition: translation arity')
                elif node.func.id not in ('gettext', '_', 'str', 'int'):
                    raise Unsupported('partition: unresolved supplier or function')
        # Native gettext source fallback uses English n==1 regardless of the
        # target plural formula; this boundary must never be omitted.
        self.add_comparison(ast.Name(id='n'), ast.Eq(), ast.Constant(1))

    @staticmethod
    def evaluate(node: ast.AST, n: int):
        """Evaluate only predicates admitted above; no input source is executed."""
        literal = GuardPartition.integer(node)
        if literal is not None:
            return literal
        if isinstance(node, ast.Constant) and type(node.value) is bool:
            return node.value
        if isinstance(node, ast.Name) and node.id == 'n':
            return n
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return n % GuardPartition.integer(node.right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not GuardPartition.evaluate(node.operand, n)
        if isinstance(node, ast.BoolOp):
            values = (bool(GuardPartition.evaluate(x, n)) for x in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare):
            ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                   ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
            left = GuardPartition.evaluate(node.left, n)
            for op, right_node in zip(node.ops, node.comparators):
                right = GuardPartition.evaluate(right_node, n)
                if not ops[type(op)](left, right):
                    return False
                left = right
            return True
        raise Unsupported('partition: unadmitted predicate during evaluation')

    def cells(self) -> list[Cell]:
        cuts = sorted(self.cuts)
        result = []
        for a, end in zip(cuts, cuts[1:]):
            b = end - 1
            for residue in range(min(self.period, b - a + 1)):
                # Enumerate consecutive residues starting at a without scanning
                # each member of the interval. A width < period uses each once.
                witness = a + residue
                result.append(Cell(a, b, self.period, witness % self.period, witness))
                if len(result) > self.max_cells:
                    raise Unsupported('partition: cell budget')
        return result


def plan_partition(program: Program, runtime: CatalogRuntime, low=0, high=200,
                   *, max_cells=20000, call_aware=True) -> PartitionPlan:
    partition = GuardPartition(low, high, max_cells=max_cells)
    partition.add_program(program)
    partition.add_plural_formula(runtime.catalog.plural_expr)
    cells = partition.cells()
    # Coalesce by source decisions, native catalog index and source-fallback
    # boundary BEFORE interpreting message calls. This avoids doing a complete
    # boundary interpretation for every residue cell. Cell work is still charged.
    groups = {}
    for cell in cells:
        n = cell.witness
        key = (tuple(bool(partition.evaluate(q, n)) for q in partition.source_predicates),
               runtime.translator.plural(n), n == 1)
        groups.setdefault(key, n)
    probes = list(groups.values())
    seen = {}
    unknown = []
    for n in probes:
        out = program.run(runtime, n, plan=True)
        key = signature(out, call_aware=call_aware)
        if key not in seen:
            seen[key] = n
            if out.status == 'unknown':
                unknown.append({'n': n, 'reason': out.error})
    return PartitionPlan((low, high), partition.period, sorted(partition.cuts),
                         cells, list(seen.values()), unknown, len(probes), len(cells), probes)
