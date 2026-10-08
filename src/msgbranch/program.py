"""A bounded, non-executing Python-AST adapter for small localization boundaries.

This is not a Python sandbox or a whole-program analyser. Imports, arbitrary
calls, loops, reflection, attribute traversal and dynamic message IDs are
rejected. Only the literal primitives admitted below are interpreted.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, asdict
import json
import operator
import re
from string import Formatter
from typing import Any
from .runtime import CatalogRuntime, named_percent_fields

class Unsupported(Exception):
    """The boundary is unknown in the declared adapter, not a passing test."""

@dataclass
class Message:
    pattern: str
    lookup: dict[str, Any]
    line: int

@dataclass
class Planned:
    """A formatting result must not drive application control flow in planning."""
    pass

@dataclass
class Outcome:
    n: int
    status: str
    output: str | None
    error: str | None
    path: list[list[Any]]
    events: list[dict[str, Any]]
    lookups: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

_SIMPLE_PERCENT = re.compile(r'%(?:\(([A-Za-z_]\w*)\))?([dsc%])')
_SIMPLE_NAME = re.compile(r'(?:[A-Za-z_]\w*|[0-9]+)?\Z')

def requirements(pattern: str, dialect: str) -> list[str]:
    """Only executed-pattern requirements; deliberately limited format grammar."""
    if dialect == 'percent':
        result: list[str] = []
        i = 0
        position = 0
        while i < len(pattern):
            if pattern[i] != '%':
                i += 1
                continue
            match = _SIMPLE_PERCENT.match(pattern, i)
            if match is None:
                raise Unsupported('percent grammar outside %s/%d/%% subset')
            name, conversion = match.groups()
            if conversion != '%':
                result.append(name if name is not None else f'@{position}')
                if name is None:
                    position += 1
            i = match.end()
        return sorted(set(result))
    result = []
    auto = 0
    for _, field, spec, conversion in Formatter().parse(pattern):
        if field is None:
            continue
        root = field.split('.', 1)[0].split('[', 1)[0]
        if field != root:
            raise Unsupported('brace attribute/index traversal outside bounded subset')
        if not _SIMPLE_NAME.fullmatch(root) or conversion not in (None, 's', 'r', 'a'):
            raise Unsupported('brace grammar outside bounded field/conversion subset')
        cleaned_spec = re.sub(r'\{[A-Za-z_]\w*[^{}]*\}', '', spec)
        if cleaned_spec and not re.fullmatch(r'[^{}]*[bcdeEfFgGnosxX%]?', cleaned_spec):
            raise Unsupported('brace format specification outside bounded subset')
        if root == '':
            result.append(f'@{auto}')
            auto += 1
        elif root.isdigit():
            result.append(f'@{root}')
        else:
            result.append(root)
        result.extend(re.findall(r'\{([A-Za-z_]\w*)[^{}]*\}', spec))
    return sorted(set(result))

def shape(value: Any) -> Any:
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise Unsupported('argument mapping keys must be strings')
        return {k: type(v).__name__ for k, v in sorted(value.items())}
    if isinstance(value, tuple):
        return [type(v).__name__ for v in value]
    return [type(value).__name__]

class Program:
    """One function message(n), finite primitive states, and named gettext calls."""
    def __init__(self, source: str, function: str = 'message'):
        if len(source) > 100_000:
            raise Unsupported('source byte budget')
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError) as exc:
            raise Unsupported(f'parse: {exc}') from exc
        if sum(1 for _ in ast.walk(tree)) > 3000:
            raise Unsupported('AST node budget')
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function]
        if len(functions) != 1:
            raise Unsupported('exactly one selected function required')
        depths = [(tree, 0)]
        while depths:
            node, depth = depths.pop()
            if depth > 50:
                raise Unsupported('AST nesting budget')
            depths.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
        self.function = functions[0]
        args = self.function.args
        if [a.arg for a in args.args] != ['n'] or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults:
            raise Unsupported('adapter signature must be message(n)')
        if self.function.decorator_list:
            raise Unsupported('decorated boundary')
        # Additional top-level imports/functions are never evaluated.
        self.source = source

    def run(self, runtime: CatalogRuntime, n: int, *, plan: bool = False) -> Outcome:
        if type(n) is not int or not 0 <= n <= 10000:
            raise ValueError('n must be an integer in 0..10000')
        self.env: dict[str, Any] = {'n': n}
        self.runtime, self.plan = runtime, plan
        self.path: list[list[Any]] = []
        self.events: list[dict[str, Any]] = []
        self.steps = 0
        runtime.reset()
        try:
            returned, value = self.block(self.function.body)
            if not returned:
                raise Unsupported('no reached return')
            if isinstance(value, Message):
                value = value.pattern
            if not isinstance(value, (str, Planned) if plan else str):
                raise Unsupported('boundary does not return a string')
            return Outcome(n, 'planned' if plan else 'ok', None if plan else value,
                           None, self.path, self.events, runtime.serialize_trace())
        except Unsupported as exc:
            return Outcome(n, 'unknown', None, str(exc), self.path, self.events, runtime.serialize_trace())
        except (KeyError, TypeError, ValueError, IndexError, OverflowError, ZeroDivisionError) as exc:
            # Formatter errors are observations, not linguistic quality judgements.
            return Outcome(n, 'error', None, f'{type(exc).__name__}: {exc}',
                           self.path, self.events, runtime.serialize_trace())

    def tick(self) -> None:
        self.steps += 1
        if self.steps > 3000:
            raise Unsupported('interpretation step budget')

    def primitive(self, value: Any) -> Any:
        if isinstance(value, (Message, Planned)) or type(value) not in (str, int, float, bool, type(None), dict, tuple, list):
            raise Unsupported('non-primitive or formatted value drives computation')
        if isinstance(value, str) and len(value) > 100_000:
            raise Unsupported('string value budget')
        if type(value) is int and abs(value) > 10**12:
            raise Unsupported('integer value budget')
        if isinstance(value, (dict, tuple, list)) and len(value) > 1000:
            raise Unsupported('container value budget')
        return value

    def block(self, nodes: list[ast.stmt]) -> tuple[bool, Any]:
        for node in nodes:
            self.tick()
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self.env[node.targets[0].id] = self.expression(node.value)
            elif isinstance(node, ast.If):
                decision = bool(self.primitive(self.expression(node.test)))
                self.path.append([node.lineno, decision])
                done, value = self.block(node.body if decision else node.orelse)
                if done:
                    return done, value
            elif isinstance(node, ast.Return):
                return True, self.expression(node.value)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue  # a docstring
            else:
                raise Unsupported(f'unsupported statement {type(node).__name__} at line {node.lineno}')
        return False, None

    def expression(self, node: ast.AST | None) -> Any:
        self.tick()
        if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool, type(None)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.env:
                raise Unsupported(f'unresolved name {node.id}')
            return self.env[node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [self.expression(x) for x in node.elts]
            return tuple(values) if isinstance(node, ast.Tuple) else values
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                raise Unsupported('dictionary expansion')
            return {self.primitive(self.expression(k)): self.primitive(self.expression(v)) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.IfExp):
            decision = bool(self.primitive(self.expression(node.test)))
            self.path.append([node.lineno, decision])
            return self.expression(node.body if decision else node.orelse)
        if isinstance(node, ast.UnaryOp):
            op = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}.get(type(node.op))
            if op is None:
                raise Unsupported('unary operator')
            return op(self.primitive(self.expression(node.operand)))
        if isinstance(node, ast.Compare):
            left = self.primitive(self.expression(node.left))
            for op_node, right_node in zip(node.ops, node.comparators):
                op = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                      ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
                      ast.In: operator.contains}.get(type(op_node))
                if op is None:
                    raise Unsupported('comparison operator')
                right = self.primitive(self.expression(right_node))
                if not (op(right, left) if isinstance(op_node, ast.In) else op(left, right)):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            for child in node.values:
                value = self.primitive(self.expression(child))
                if isinstance(node.op, ast.And) and not value:
                    return value
                if isinstance(node.op, ast.Or) and value:
                    return value
            return value
        if isinstance(node, ast.BinOp):
            left, right = self.expression(node.left), self.expression(node.right)
            if isinstance(left, Message) and isinstance(node.op, ast.Mod):
                return self.format_message(left, right, {}, 'percent', node.lineno)
            if isinstance(node.op, ast.Mod) and type(left) is str:
                raise Unsupported('formatting an untracked string')
            op = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mod: operator.mod}.get(type(node.op))
            if op is None:
                raise Unsupported('binary operator')
            return self.primitive(op(self.primitive(left), self.primitive(right)))
        if isinstance(node, ast.Call):
            return self.call(node)
        raise Unsupported(f'unsupported expression {type(node).__name__}')

    def call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Name) and node.func.id in ('gettext', '_', 'ngettext', 'pgettext', 'npgettext'):
            expected = {'gettext': 1, '_': 1, 'ngettext': 3, 'pgettext': 2, 'npgettext': 4}[node.func.id]
            if len(node.args) != expected or node.keywords:
                raise Unsupported('translation call arity/keywords')
            literal_count = {'gettext': 1, '_': 1, 'ngettext': 2, 'pgettext': 2, 'npgettext': 3}[node.func.id]
            if not all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in node.args[:literal_count]):
                raise Unsupported('dynamic message identifier or context')
            args = [self.expression(x) for x in node.args]
            if node.func.id == 'ngettext' and type(args[2]) is not int:
                raise Unsupported('noninteger selector outside gettext adapter')
            if node.func.id == 'npgettext' and type(args[3]) is not int:
                raise Unsupported('noninteger selector outside gettext adapter')
            runtime_call = {
                'gettext': self.runtime.gettext,
                '_': self.runtime.gettext,
                'ngettext': self.runtime.ngettext,
                'pgettext': self.runtime.pgettext,
                'npgettext': self.runtime.npgettext,
            }[node.func.id]
            pattern = runtime_call(*args)
            return Message(pattern, self.runtime.serialize_trace()[-1], node.lineno)
        if isinstance(node.func, ast.Name) and node.func.id in ('str', 'int') and len(node.args) == 1 and not node.keywords:
            value = self.primitive(self.expression(node.args[0]))
            if type(value) not in (str, int, float, bool):
                raise Unsupported('conversion input')
            return str(value) if node.func.id == 'str' else int(value)
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
            message = self.expression(node.func.value)
            if not isinstance(message, Message):
                raise Unsupported('format on an untracked value')
            if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args):
                raise Unsupported('format argument expansion')
            args = tuple(self.primitive(self.expression(x)) for x in node.args)
            kwargs = {k.arg: self.primitive(self.expression(k.value)) for k in node.keywords}
            return self.format_message(message, args, kwargs, 'brace', node.lineno)
        raise Unsupported(f'unsupported or dynamic call at line {node.lineno}')

    def format_message(self, message: Message, args: Any, kwargs: dict[str, Any], dialect: str, line: int) -> Any:
        self.primitive(args)
        needed = requirements(message.pattern, dialect)
        supplied_shape = {'args': shape(args), 'kwargs': shape(kwargs)} if dialect == 'brace' else shape(args)
        event = {'line': line, 'lookup_line': message.line, 'pattern': message.pattern,
                 'dialect': dialect, 'needed': needed, 'supplied_shape': supplied_shape,
                 'lookup': message.lookup}
        self.events.append(event)
        if self.plan:
            return Planned()
        return message.pattern % args if dialect == 'percent' else message.pattern.format(*args, **kwargs)


def signature(outcome: Outcome, *, call_aware: bool = True) -> str:
    # Exact pattern is necessary: source fallback selection need not agree with
    # the catalog locale's plural index (notably one-form locales).
    lookups = [{k: value[k] for k in ('method', 'singular', 'plural', 'branch', 'resolution', 'output')}
               for value in outcome.lookups]
    result: dict[str, Any] = {'lookups': lookups, 'status': outcome.status, 'unknown': outcome.error}
    if call_aware:
        result['path'] = outcome.path
        result['events'] = [{k: e[k] for k in ('line', 'lookup_line', 'pattern', 'dialect', 'needed', 'supplied_shape')}
                            for e in outcome.events]
    return json.dumps(result, sort_keys=True, ensure_ascii=False)


def representatives(program: Program, runtime: CatalogRuntime, domain: list[int], *, call_aware: bool = True):
    """Enumerate a bounded domain; contract, do not solve, its execution shapes."""
    if not domain or len(domain) > 10001 or any(type(n) is not int or not 0 <= n <= 10000 for n in domain):
        raise ValueError('nonempty bounded integer domain required')
    seen: dict[str, int] = {}
    unknown: list[dict[str, Any]] = []
    for n in domain:
        result = program.run(runtime, n, plan=True)
        key = signature(result, call_aware=call_aware)
        if key not in seen:
            seen[key] = n
            if result.status == 'unknown':
                unknown.append({'n': n, 'reason': result.error})
    return list(seen.values()), unknown
