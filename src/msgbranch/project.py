"""Static project-level qualification for gettext call/catalog boundaries.

The scanner never imports the target project.  It combines four deliberately
separate observations:

* literal gettext-family lookup recovery;
* bounded intraprocedural def-use recovery for a translation result that is
  formatted later;
* witness-conditioned supplier recovery for simple branches over the plural
  count; and
* real PO -> MO compilation plus Python ``GNUTranslations`` branch selection.

Dynamic identifiers, indirect calls, unresolved mappings and unsupported
control flow remain explicit ``unknown`` results rather than passes.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import re
from string import Formatter
from typing import Any, Iterable, Mapping

from .runtime import CatalogRuntime

_PERCENT = re.compile(
    r"%(?:\(([^)]+)\))?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?([diouxXeEfFgGcrsa%])"
)


@dataclass(frozen=True)
class Supplier:
    status: str
    mode: str
    names: tuple[str, ...] = ()
    positional: int = 0
    reason: str | None = None
    named_types: tuple[tuple[str, str], ...] = ()
    positional_types: tuple[str, ...] = ()
    is_mapping: bool = False


@dataclass(frozen=True)
class CallSite:
    path: str
    line: int
    column: int
    callee: str
    kind: str
    singular: str | None
    plural: str | None
    supplier: Supplier
    status: str
    reason: str | None = None
    context: str | None = None
    count_binding: str = "domain"
    count_literal: int | None = None


@dataclass(frozen=True)
class PatternRequirements:
    status: str
    dialect: str
    names: tuple[str, ...] = ()
    positional: int = 0
    reason: str | None = None
    named_types: tuple[tuple[str, str], ...] = ()
    positional_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class _TranslationShape:
    kind: str
    base_arity: int
    context_index: int | None
    singular_index: int
    plural_index: int | None
    count_index: int | None


# Internal abstract values used only by the non-executing flow recovery.
@dataclass(frozen=True)
class _Unknown:
    reason: str


@dataclass(frozen=True)
class _Primitive:
    type_name: str
    literal: Any = None
    has_literal: bool = False
    symbol: str | None = None


@dataclass(frozen=True)
class _MappingValue:
    items: tuple[tuple[str, Any], ...]
    unknown_keys: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class _SequenceValue:
    items: tuple[Any, ...]
    unknown_items: bool = False
    is_tuple: bool = True


@dataclass(frozen=True)
class _FormatArgsValue:
    positional: tuple[Any, ...]
    keywords: tuple[tuple[str, Any], ...]
    expanded: bool = False


@dataclass(frozen=True)
class _ConditionalValue:
    test: ast.AST
    env: tuple[tuple[str, Any], ...]
    when_true: Any
    when_false: Any


@dataclass(frozen=True)
class _MessageValue:
    line: int
    column: int
    count_var: str | None


@dataclass(frozen=True)
class _FlowModel:
    lookup_line: int
    lookup_column: int
    use_line: int
    use_column: int
    mode: str
    value: Any
    count_var: str | None
    reachable: Any = True


@dataclass(frozen=True)
class _FlowResolution:
    supplier: Supplier
    use_lines: tuple[int, ...]
    reason: str | None = None
    reachable: bool | None = True


def _callee_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _translation_shape(
    call: ast.Call,
    callee: str | None,
    singulars: set[str],
    plurals: set[str],
    overloaded: set[str],
    contextual_singulars: set[str],
    contextual_plurals: set[str],
) -> _TranslationShape | None:
    if callee in contextual_plurals:
        return _TranslationShape("plural", 4, 0, 1, 2, 3)
    if callee in contextual_singulars:
        return _TranslationShape("singular", 2, 0, 1, None, None)
    if callee in plurals:
        return _TranslationShape("plural", 3, None, 0, 1, 2)
    if callee in overloaded:
        if len(call.args) >= 3:
            return _TranslationShape("plural", 3, None, 0, 1, 2)
        return _TranslationShape("singular", 1, None, 0, None, None)
    if callee in singulars:
        return _TranslationShape("singular", 1, None, 0, None, None)
    return None


def _primitive_type(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "finite-float" if math.isfinite(value) else "nonfinite-float"
        if isinstance(value, str):
            return "str"
        if value is None:
            return "none"
    if isinstance(node, ast.JoinedStr):
        return "str"
    if isinstance(node, ast.Compare):
        return "bool"
    if isinstance(node, ast.BoolOp):
        return "unknown"  # and/or return operands, not necessarily bools.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return {"str": "str", "int": "int", "float": "float", "bool": "bool", "len": "int"}.get(
            node.func.id, "unknown"
        )
    return "unknown"


def _mapping_supplier(node: ast.AST, mode: str) -> Supplier:
    if isinstance(node, ast.Dict):
        names: list[str] = []
        types: list[tuple[str, str]] = []
        for key, value_node in zip(node.keys, node.values, strict=True):
            if key is None:
                return Supplier("unknown", mode, reason="mapping expansion")
            value = _literal_string(key)
            if value is None:
                return Supplier("unknown", mode, reason="dynamic mapping key")
            names.append(value)
            types.append((value, _primitive_type(value_node)))
        return Supplier("known", mode, tuple(sorted(set(names))), named_types=tuple(sorted(types)), is_mapping=True)
    if isinstance(node, ast.List):
        return Supplier("unknown", mode, reason="percent list supplier is not a positional tuple")
    if isinstance(node, ast.Tuple):
        if any(isinstance(x, ast.Starred) for x in node.elts):
            return Supplier("unknown", mode, reason="positional expansion")
        return Supplier(
            "known",
            mode,
            positional=len(node.elts),
            positional_types=tuple(_primitive_type(x) for x in node.elts),
        )
    if isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.IfExp)):
        return Supplier("unknown", mode, reason="dynamic formatting supplier")
    return Supplier("known", mode, positional=1, positional_types=(_primitive_type(node),))


def _format_supplier(node: ast.Call) -> Supplier:
    if any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords):
        return Supplier("unknown", "str.format", reason="argument expansion")
    names = tuple(sorted(k.arg for k in node.keywords if k.arg is not None))
    return Supplier(
        "known",
        "str.format",
        names,
        len(node.args),
        named_types=tuple(sorted((k.arg, _primitive_type(k.value)) for k in node.keywords if k.arg is not None)),
        positional_types=tuple(_primitive_type(x) for x in node.args),
    )


def _direct_supplier(call: ast.Call, parents: dict[ast.AST, ast.AST], base_arity: int) -> Supplier:
    # Flask-Babel/Jinja new-style gettext accepts interpolation variables on the
    # translation call.  We record this as an explicit binding assumption rather
    # than claiming every function named ngettext has that API.
    keyword_names = tuple(sorted(k.arg for k in call.keywords if k.arg is not None))
    if any(k.arg is None for k in call.keywords):
        return Supplier("unknown", "call-keywords", reason="keyword expansion")
    if keyword_names:
        return Supplier(
            "known",
            "call-keywords",
            keyword_names,
            named_types=tuple(sorted((k.arg, _primitive_type(k.value)) for k in call.keywords if k.arg is not None)),
        )

    parent = parents.get(call)
    if isinstance(parent, ast.BinOp) and parent.left is call and isinstance(parent.op, ast.Mod):
        return _mapping_supplier(parent.right, "percent")
    if isinstance(parent, ast.Attribute) and parent.value is call and parent.attr == "format":
        grandparent = parents.get(parent)
        if isinstance(grandparent, ast.Call) and grandparent.func is parent:
            return _format_supplier(grandparent)
        return Supplier("unknown", "str.format", reason="format attribute not called directly")

    if len(call.args) > base_arity:
        return Supplier("unknown", "translation-call", reason="extra positional translation arguments")
    return Supplier("none", "none")


def scan_source(
    source: str,
    path: str,
    *,
    singular_callees: Iterable[str] = ("gettext", "_"),
    plural_callees: Iterable[str] = ("ngettext",),
    overloaded_callees: Iterable[str] = (),
    contextual_singular_callees: Iterable[str] = ("pgettext",),
    contextual_plural_callees: Iterable[str] = ("npgettext",),
) -> list[CallSite]:
    if len(source.encode("utf-8")) > 1_000_000:
        return [
            CallSite(
                path,
                0,
                0,
                "",
                "unknown",
                None,
                None,
                Supplier("unknown", "none", reason="file-size budget"),
                "unknown",
                "source exceeds 1 MB budget",
            )
        ]
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, RecursionError) as exc:
        return [
            CallSite(
                path,
                getattr(exc, "lineno", 0) or 0,
                0,
                "",
                "unknown",
                None,
                None,
                Supplier("unknown", "none", reason="parse failure"),
                "unknown",
                f"parse: {exc}",
            )
        ]
    nodes = list(ast.walk(tree))
    if len(nodes) > 40_000:
        return [
            CallSite(
                path,
                0,
                0,
                "",
                "unknown",
                None,
                None,
                Supplier("unknown", "none", reason="AST budget"),
                "unknown",
                "AST exceeds 40,000-node budget",
            )
        ]
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    singulars = set(singular_callees)
    plurals = set(plural_callees)
    overloaded = set(overloaded_callees)
    contextual_singulars = set(contextual_singular_callees)
    contextual_plurals = set(contextual_plural_callees)
    calls: list[CallSite] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        callee = _callee_name(node.func)
        shape = _translation_shape(
            node,
            callee,
            singulars,
            plurals,
            overloaded,
            contextual_singulars,
            contextual_plurals,
        )
        if shape is None:
            continue
        supplier = _direct_supplier(node, parents, shape.base_arity)
        if len(node.args) < shape.base_arity:
            calls.append(
                CallSite(
                    path,
                    node.lineno,
                    node.col_offset,
                    callee or "",
                    shape.kind,
                    None,
                    None,
                    supplier,
                    "unknown",
                    "translation call has too few positional arguments",
                )
            )
            continue
        context = _literal_string(node.args[shape.context_index]) if shape.context_index is not None else None
        singular = _literal_string(node.args[shape.singular_index])
        plural = _literal_string(node.args[shape.plural_index]) if shape.plural_index is not None else None
        if (
            singular is None
            or (shape.kind == "plural" and plural is None)
            or (shape.context_index is not None and context is None)
        ):
            calls.append(
                CallSite(
                    path,
                    node.lineno,
                    node.col_offset,
                    callee or "",
                    shape.kind,
                    singular,
                    plural,
                    supplier,
                    "unknown",
                    "dynamic message identifier or context",
                    context,
                )
            )
            continue
        count_binding = "domain"
        count_literal = None
        if shape.count_index is not None:
            selector = node.args[shape.count_index]
            if isinstance(selector, ast.Constant) and type(selector.value) is int:
                count_binding, count_literal = "fixed", selector.value
            elif not isinstance(selector, ast.Name):
                count_binding = "unknown"
        calls.append(
            CallSite(
                path,
                node.lineno,
                node.col_offset,
                callee or "",
                shape.kind,
                singular,
                plural,
                supplier,
                "literal",
                context=context,
                count_binding=count_binding,
                count_literal=count_literal,
            )
        )
    return sorted(calls, key=lambda c: (c.path, c.line, c.column))


def _annotation_type(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return {"int": "int", "str": "str", "float": "float", "bool": "bool"}.get(node.id, "unknown")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {"int": "int", "str": "str", "float": "float", "bool": "bool"}.get(node.value, "unknown")
    return "unknown"


class _FlowScanner:
    """A bounded intraprocedural abstract interpreter for formatting shapes.

    It tracks only local values required to connect a gettext lookup with a
    later percent/``str.format`` use.  It does not execute target code, resolve
    arbitrary calls, infer heap state, or cross function boundaries.
    """

    def __init__(
        self,
        *,
        singulars: set[str],
        plurals: set[str],
        overloaded: set[str],
        contextual_singulars: set[str],
        contextual_plurals: set[str],
    ) -> None:
        self.singulars = singulars
        self.plurals = plurals
        self.overloaded = overloaded
        self.contextual_singulars = contextual_singulars
        self.contextual_plurals = contextual_plurals
        self.models: dict[tuple[int, int], list[_FlowModel]] = {}
        self.reachable: Any = True

    def _shape(self, call: ast.Call) -> _TranslationShape | None:
        return _translation_shape(
            call,
            _callee_name(call.func),
            self.singulars,
            self.plurals,
            self.overloaded,
            self.contextual_singulars,
            self.contextual_plurals,
        )

    def scan(self, tree: ast.AST) -> dict[tuple[int, int], list[_FlowModel]]:
        if isinstance(tree, ast.Module):
            self._block(tree.body, {})
        # The syntax scanner also sees calls after a terminating return. Keep
        # their explicit unreachable model; never fall back to direct syntax.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and self._shape(node) is not None:
                self.models.setdefault((node.lineno, node.col_offset), [
                    _FlowModel(node.lineno, node.col_offset, node.lineno,
                               node.col_offset, "lookup", None, None, False)
                ])
        return self.models

    def _function_env(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
        env: dict[str, Any] = {}
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        for arg in args:
            env[arg.arg] = _Primitive(_annotation_type(arg.annotation), symbol=arg.arg)
        if node.args.vararg:
            env[node.args.vararg.arg] = _Unknown("variadic positional parameter")
        if node.args.kwarg:
            env[node.args.kwarg.arg] = _Unknown("variadic keyword parameter")
        return env

    def _merge_env(self, test: ast.AST, before: dict[str, Any],
                   true_env: dict[str, Any], false_env: dict[str, Any]) -> dict[str, Any]:
        snapshot = tuple(sorted(before.items()))
        merged = {}
        for name in sorted(set(before) | set(true_env) | set(false_env)):
            left = true_env.get(name, before.get(name, _Unknown("unbound on true branch")))
            right = false_env.get(name, before.get(name, _Unknown("unbound on false branch")))
            merged[name] = left if left == right else _ConditionalValue(test, snapshot, left, right)
        return merged

    def _conditional(self, test: ast.AST, env: dict[str, Any], when_true: Any, when_false: Any) -> Any:
        """Fork abstract evaluation only; target expressions are never executed."""
        before = dict(env)
        snapshot = tuple(sorted(before.items()))
        known = _condition(test, before, None, None)
        if known is not None:
            return (when_true if known else when_false)(env)
        previous = self.reachable
        true_env, false_env = dict(before), dict(before)
        self.reachable = _ConditionalValue(test, snapshot, previous, False)
        left = when_true(true_env)
        self.reachable = _ConditionalValue(test, snapshot, False, previous)
        right = when_false(false_env)
        self.reachable = previous
        env.clear()
        env.update(self._merge_env(test, before, true_env, false_env))
        return _ConditionalValue(test, snapshot, left, right)

    def _block(self, statements: list[ast.stmt], env: dict[str, Any]) -> dict[str, Any] | None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                previous = self.reachable
                self.reachable = True
                self._block(statement.body, self._function_env(statement))
                self.reachable = previous
                continue
            if isinstance(statement, ast.ClassDef):
                self._block(statement.body, {})
                continue
            if isinstance(statement, ast.Assign):
                value = self._expr(statement.value, env)
                for target in statement.targets:
                    self._bind(target, value, env)
                continue
            if isinstance(statement, ast.AnnAssign):
                value = self._expr(statement.value, env) if statement.value is not None else _Primitive(
                    _annotation_type(statement.annotation)
                )
                self._bind(statement.target, value, env)
                continue
            if isinstance(statement, ast.AugAssign):
                self._expr(statement.target, env)
                self._expr(statement.value, env)
                self._bind(statement.target, _Unknown("augmented assignment result"), env)
                continue
            if isinstance(statement, ast.Delete):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = _Unknown("deleted binding")
                    else:
                        self._expr(target, env)
                        self._invalidate_container(target, env, "unsupported container deletion")
                continue
            if isinstance(statement, (ast.Return, ast.Expr)):
                value_node = statement.value
                if value_node is not None:
                    self._expr(value_node, env)
                if isinstance(statement, ast.Return):
                    return None
                continue
            if isinstance(statement, ast.If):
                self._expr(statement.test, env)
                before = dict(env)
                previous = self.reachable
                snapshot = tuple(sorted(before.items()))
                self.reachable = _ConditionalValue(statement.test, snapshot, previous, False)
                body_env = self._block(statement.body, dict(before))
                body_reachable = self.reachable if body_env is not None else False
                self.reachable = _ConditionalValue(statement.test, snapshot, False, previous)
                else_env = self._block(statement.orelse, dict(before)) if statement.orelse else dict(before)
                else_reachable = self.reachable if else_env is not None else False
                self.reachable = _ConditionalValue(statement.test, snapshot, body_reachable, else_reachable)
                if body_env is None and else_env is None:
                    return None
                if body_env is None:
                    merged = else_env
                elif else_env is None:
                    merged = body_env
                else:
                    merged = self._merge_env(statement.test, before, body_env, else_env)
                env.clear()
                env.update(merged)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                self._expr(statement.test if isinstance(statement, ast.While) else statement.iter, env)
                previous = self.reachable
                self.reachable = _Unknown("unsupported loop reachability")
                body_env = self._block(statement.body, dict(env)) or {}
                self.reachable = _Unknown("unsupported loop reachability")
                self._block(statement.orelse, dict(env))
                self.reachable = previous
                for name, value in body_env.items():
                    if env.get(name) != value:
                        env[name] = _Unknown("loop-dependent value")
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    self._expr(item.context_expr, env)
                self.reachable = _Unknown("unsupported context-manager reachability")
                self._block(statement.body, env)
                continue
            if isinstance(statement, ast.Try):
                self.reachable = _Unknown("unsupported exception reachability")
                branches = [self._block(statement.body, dict(env)) or {}]
                branches.extend(self._block(handler.body, dict(env)) or {} for handler in statement.handlers)
                if statement.orelse:
                    branches.append(self._block(statement.orelse, dict(env)) or {})
                if statement.finalbody:
                    branches = [self._block(statement.finalbody, branch) or {} for branch in branches]
                for name in set().union(*(set(branch) for branch in branches)):
                    values = [branch.get(name, _Unknown("unbound try branch")) for branch in branches]
                    env[name] = values[0] if all(value == values[0] for value in values) else _Unknown(
                        "try-dependent value"
                    )
                continue
            if isinstance(statement, ast.Match):
                self._expr(statement.subject, env)
                self.reachable = _Unknown("unsupported match reachability")
                case_envs = [self._block(case.body, dict(env)) or {} for case in statement.cases]
                for name in set().union(*(set(branch) for branch in case_envs)):
                    values = [branch.get(name, _Unknown("unbound match case")) for branch in case_envs]
                    env[name] = values[0] if all(value == values[0] for value in values) else _Unknown(
                        "match-dependent value"
                    )
                continue
            if isinstance(statement, (ast.Pass, ast.Import, ast.ImportFrom)):
                continue
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.expr):
                    self._expr(child, env)
            self.reachable = _Unknown(f"unsupported statement {type(statement).__name__}")
        return env

    def _bind(self, target: ast.AST, value: Any, env: dict[str, Any]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, _SequenceValue):
            if len(target.elts) == len(value.items):
                for child, item in zip(target.elts, value.items, strict=True):
                    self._bind(child, item, env)
            else:
                for child in target.elts:
                    self._bind(child, _Unknown("unpack arity"), env)
        elif isinstance(target, (ast.Subscript, ast.Attribute)):
            self._expr(target, env)
            self._invalidate_container(target, env, "unsupported container assignment")

    def _invalidate_container(self, node: ast.AST, env: dict[str, Any], reason: str) -> None:
        while isinstance(node, (ast.Subscript, ast.Attribute)):
            node = node.value
        if not isinstance(node, ast.Name):
            return
        target = env.get(node.id)
        if not isinstance(target, (_MappingValue, _SequenceValue, _ConditionalValue)):
            return
        def contains(value: Any) -> bool:
            if value is target:
                return True
            if isinstance(value, _ConditionalValue):
                return contains(value.when_true) or contains(value.when_false)
            if isinstance(value, _MappingValue):
                return any(contains(item) for _, item in value.items)
            if isinstance(value, _SequenceValue):
                return any(contains(item) for item in value.items)
            return False
        for name, value in list(env.items()):
            if contains(value):
                env[name] = _Unknown(reason)

    def _record(self, message: _MessageValue, mode: str, value: Any, node: ast.AST) -> None:
        key = (message.line, message.column)
        self.models.setdefault(key, []).append(
            _FlowModel(message.line, message.column, node.lineno, node.col_offset,
                       mode, value, message.count_var, self.reachable)
        )

    def _expr(self, node: ast.AST | None, env: dict[str, Any]) -> Any:
        if node is None:
            return _Unknown("missing expression")
        if isinstance(node, ast.Constant):
            type_name = _primitive_type(node)
            return _Primitive(type_name, node.value, True)
        if isinstance(node, ast.Name):
            return env.get(node.id, _Primitive("unknown", symbol=node.id))
        if isinstance(node, ast.JoinedStr):
            for child in node.values:
                if isinstance(child, ast.FormattedValue):
                    self._expr(child.value, env)
                    self._expr(child.format_spec, env)
            return _Primitive("str")
        if isinstance(node, ast.Dict):
            items: list[tuple[str, Any]] = []
            reason = None
            for key, value in zip(node.keys, node.values, strict=True):
                self._expr(key, env)
                item = self._expr(value, env)
                literal = _literal_string(key)
                if key is None or literal is None:
                    reason = "mapping expansion or dynamic mapping key"
                else:
                    items.append((literal, item))
            return _MappingValue(tuple(items), reason is not None, reason)
        if isinstance(node, (ast.Tuple, ast.List)):
            items = tuple(self._expr(item.value if isinstance(item, ast.Starred) else item, env)
                          for item in node.elts)
            return _SequenceValue(items, any(isinstance(item, ast.Starred) for item in node.elts),
                                  isinstance(node, ast.Tuple))
        if isinstance(node, ast.IfExp):
            self._expr(node.test, env)
            return self._conditional(node.test, env, lambda e: self._expr(node.body, e),
                                     lambda e: self._expr(node.orelse, e))
        if isinstance(node, ast.UnaryOp):
            operand = self._expr(node.operand, env)
            if isinstance(node.op, ast.Not):
                return _Primitive("bool")
            if isinstance(operand, _Primitive) and operand.type_name in {"int", "float", "number"}:
                return _Primitive(operand.type_name)
            return _Primitive("unknown")
        if isinstance(node, ast.BoolOp):
            first = self._expr(node.values[0], env)
            rest = node.values[1] if len(node.values) == 2 else ast.BoolOp(op=node.op, values=node.values[1:])
            later = lambda e: self._expr(rest, e)
            retained = lambda e: first
            return self._conditional(node.values[0], env,
                                     later if isinstance(node.op, ast.And) else retained,
                                     retained if isinstance(node.op, ast.And) else later)
        if isinstance(node, ast.Compare):
            self._expr(node.left, env)
            for child in node.comparators:
                self._expr(child, env)
            return _Primitive("bool")
        if isinstance(node, ast.BinOp):
            left = self._expr(node.left, env)
            right = self._expr(node.right, env)
            if isinstance(node.op, ast.Mod) and isinstance(left, _MessageValue):
                self._record(left, "percent", right, node)
                return _Primitive("str")
            if isinstance(node.op, ast.Add):
                if isinstance(left, _Primitive) and isinstance(right, _Primitive):
                    if left.type_name == right.type_name == "str":
                        return _Primitive("str")
                    if left.type_name == right.type_name == "int":
                        return _Primitive("int")
                    if left.type_name in {"int", "float", "number"} and right.type_name in {
                        "int",
                        "float",
                        "number",
                    }:
                        return _Primitive("number")
            if isinstance(node.op, (ast.Sub, ast.Mult, ast.FloorDiv, ast.Div, ast.Pow)):
                if isinstance(left, _Primitive) and isinstance(right, _Primitive):
                    if left.type_name == right.type_name == "int" and not isinstance(node.op, ast.Div):
                        return _Primitive("int")
                    if left.type_name in {"int", "float", "number"} and right.type_name in {
                        "int",
                        "float",
                        "number",
                    }:
                        return _Primitive("number")
            return _Primitive("unknown")
        if isinstance(node, ast.Call):
            shape = self._shape(node)
            base = self._expr(node.func.value, env) if isinstance(node.func, ast.Attribute) else None
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                self._expr(node.func, env)
            arguments = tuple(self._expr(arg.value if isinstance(arg, ast.Starred) else arg, env)
                              for arg in node.args)
            keywords = tuple((keyword.arg or "", self._expr(keyword.value, env)) for keyword in node.keywords)
            if shape is not None:
                if len(node.args) < shape.base_arity:
                    return _Unknown("translation call arity")
                if _literal_string(node.args[shape.singular_index]) is None:
                    return _Unknown("dynamic message identifier")
                if shape.plural_index is not None and _literal_string(node.args[shape.plural_index]) is None:
                    return _Unknown("dynamic plural identifier")
                if shape.context_index is not None and _literal_string(node.args[shape.context_index]) is None:
                    return _Unknown("dynamic context")
                count_var = None
                if shape.count_index is not None:
                    count_node = node.args[shape.count_index]
                    if isinstance(count_node, ast.Name):
                        count_var = count_node.id
                        env[count_var] = _Primitive("int", symbol=count_var)
                message = _MessageValue(node.lineno, node.col_offset, count_var)
                self._record(message, "lookup", None, node)
                if any(keyword.arg is None for keyword in node.keywords):
                    self._record(message, "call-keywords", _Unknown("keyword expansion"), node)
                    return _Primitive("str")
                if node.keywords:
                    mapping = _MappingValue(keywords)
                    self._record(message, "call-keywords", mapping, node)
                    return _Primitive("str")
                return message

            if isinstance(node.func, ast.Name):
                if node.func.id in {"str", "int", "float", "bool"} and len(node.args) == 1 and not node.keywords:
                    return _Primitive(node.func.id)
                if node.func.id == "len" and len(node.args) == 1 and not node.keywords:
                    return _Primitive("int")
                if node.func.id == "dict" and not node.args and all(keyword.arg is not None for keyword in node.keywords):
                    return _MappingValue(keywords)
            if isinstance(node.func, ast.Attribute):
                if isinstance(base, _MessageValue) and node.func.attr == "format":
                    value = _FormatArgsValue(
                        arguments,
                        keywords,
                        any(isinstance(arg, ast.Starred) for arg in node.args) or any(keyword.arg is None for keyword in node.keywords),
                    )
                    self._record(base, "str.format", value, node)
                    return _Primitive("str")
                if isinstance(base, _MessageValue) and node.func.attr == "format_map":
                    value = arguments[0] if len(node.args) == 1 and not node.keywords else _Unknown(
                        "format_map arity"
                    )
                    self._record(base, "format_map", value, node)
                    return _Primitive("str")
                self._invalidate_container(node.func.value, env, "unsupported container method or escape")
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                self._invalidate_container(argument, env, "container passed to unresolved call")
            return _Primitive("unknown")
        if isinstance(node, ast.NamedExpr):
            value = self._expr(node.value, env)
            self._bind(node.target, value, env)
            return value
        # Unsupported evaluated expressions may still mutate or escape a local
        # supplier through their children. Recover effects, not a guessed type.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self._expr(child, env)
        return _Primitive("unknown")


def _env_dict(items: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    return dict(items)


def _value_scalar(value: Any, count_var: str | None, count: int | None) -> Any:
    if type(value) is bool:
        return value
    if isinstance(value, _Primitive):
        if value.has_literal:
            return value.literal
        if count_var is not None and value.symbol == count_var and count is not None:
            return count
    if isinstance(value, _ConditionalValue):
        branch = _condition(value.test, _env_dict(value.env), count_var, count)
        if branch is not None:
            return _value_scalar(value.when_true if branch else value.when_false, count_var, count)
        left = _value_scalar(value.when_true, count_var, count)
        right = _value_scalar(value.when_false, count_var, count)
        return left if type(left) is type(right) and left == right else None
    return None


def _scalar(node: ast.AST, env: Mapping[str, Any], count_var: str | None, count: int | None) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if count_var is not None and node.id == count_var and count is not None:
            return count
        return _value_scalar(env.get(node.id), count_var, count)
    if isinstance(node, ast.Compare):
        return _condition(node, env, count_var, count)
    if isinstance(node, ast.BoolOp):
        for child in node.values:
            value = _scalar(child, env, count_var, count)
            if value is None:
                return None
            if isinstance(node.op, ast.And) and not value:
                return value
            if isinstance(node.op, ast.Or) and value:
                return value
        return value
    if isinstance(node, ast.UnaryOp):
        value = _scalar(node.operand, env, count_var, count)
        if value is None:
            return None
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        return None
    if isinstance(node, ast.BinOp):
        left = _scalar(node.left, env, count_var, count)
        right = _scalar(node.right, env, count_var, count)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1 and not node.keywords:
        value = _scalar(node.args[0], env, count_var, count)
        if value is None:
            return None
        try:
            if node.func.id == "int":
                return int(value)
            if node.func.id == "str":
                return str(value)
            if node.func.id == "float":
                return float(value)
            if node.func.id == "bool":
                return bool(value)
        except (TypeError, ValueError):
            return None
    return None


def _condition(node: ast.AST, env: Mapping[str, Any], count_var: str | None, count: int | None) -> bool | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _condition(node.operand, env, count_var, count)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [_condition(child, env, count_var, count) for child in node.values]
        if isinstance(node.op, ast.And):
            if False in values:
                return False
            return True if all(value is True for value in values) else None
        if isinstance(node.op, ast.Or):
            if True in values:
                return True
            return False if all(value is False for value in values) else None
    if isinstance(node, ast.Compare):
        left = _scalar(node.left, env, count_var, count)
        if left is None:
            return None
        current = left
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = _scalar(comparator, env, count_var, count)
            if right is None:
                return None
            try:
                ok = {
                    ast.Eq: current == right,
                    ast.NotEq: current != right,
                    ast.Lt: current < right,
                    ast.LtE: current <= right,
                    ast.Gt: current > right,
                    ast.GtE: current >= right,
                    ast.Is: current is right,
                    ast.IsNot: current is not right,
                }.get(type(operator))
            except TypeError:
                return None
            if ok is None or not ok:
                return False if ok is not None else None
            current = right
        return True
    scalar = _scalar(node, env, count_var, count)
    return bool(scalar) if scalar is not None else None


def _abstract_type(value: Any, count_var: str | None, count: int | None) -> str:
    if isinstance(value, _Primitive):
        if value.symbol == count_var and count is not None:
            return "int"
        return value.type_name
    if isinstance(value, _ConditionalValue):
        branch = _condition(value.test, _env_dict(value.env), count_var, count)
        if branch is True:
            return _abstract_type(value.when_true, count_var, count)
        if branch is False:
            return _abstract_type(value.when_false, count_var, count)
        left = _abstract_type(value.when_true, count_var, count)
        right = _abstract_type(value.when_false, count_var, count)
        return left if left == right else "unknown"
    return "unknown"


def _supplier_from_value(value: Any, mode: str, count_var: str | None, count: int | None) -> Supplier:
    if isinstance(value, _ConditionalValue):
        branch = _condition(value.test, _env_dict(value.env), count_var, count)
        if branch is True:
            return _supplier_from_value(value.when_true, mode, count_var, count)
        if branch is False:
            return _supplier_from_value(value.when_false, mode, count_var, count)
        left = _supplier_from_value(value.when_true, mode, count_var, count)
        right = _supplier_from_value(value.when_false, mode, count_var, count)
        if left == right:
            return left
        return Supplier("unknown", mode, reason="supplier branch condition is not count-resolvable")
    if isinstance(value, _Unknown):
        return Supplier("unknown", mode, reason=value.reason)
    if isinstance(value, _MappingValue):
        if value.unknown_keys:
            return Supplier("unknown", mode, reason=value.reason or "unknown mapping keys")
        names = tuple(sorted({name for name, _ in value.items}))
        types = tuple(sorted((name, _abstract_type(item, count_var, count)) for name, item in value.items))
        return Supplier("known", mode, names, named_types=types, is_mapping=True)
    if isinstance(value, _SequenceValue):
        if mode == "percent" and not value.is_tuple:
            return Supplier("unknown", mode, reason="percent list supplier is not a positional tuple")
        if value.unknown_items:
            return Supplier("unknown", mode, reason="positional expansion")
        types = tuple(_abstract_type(item, count_var, count) for item in value.items)
        return Supplier("known", mode, positional=len(value.items), positional_types=types)
    if isinstance(value, _FormatArgsValue):
        if value.expanded:
            return Supplier("unknown", mode, reason="format argument expansion")
        names = tuple(sorted({name for name, _ in value.keywords}))
        named_types = tuple(sorted((name, _abstract_type(item, count_var, count)) for name, item in value.keywords))
        positional_types = tuple(_abstract_type(item, count_var, count) for item in value.positional)
        return Supplier(
            "known",
            mode,
            names,
            len(value.positional),
            named_types=named_types,
            positional_types=positional_types,
        )
    if isinstance(value, _Primitive):
        primitive_type = _abstract_type(value, count_var, count)
        if primitive_type == "unknown":
            return Supplier("unknown", mode, reason="dynamic formatting supplier")
        return Supplier(
            "known",
            mode,
            positional=1,
            positional_types=(primitive_type,),
        )
    return Supplier("unknown", mode, reason="unresolved supplier value")


def _recover_flow_models(
    source: str,
    *,
    singular_callees: Iterable[str],
    plural_callees: Iterable[str],
    overloaded_callees: Iterable[str],
    contextual_singular_callees: Iterable[str],
    contextual_plural_callees: Iterable[str],
) -> dict[tuple[int, int], list[_FlowModel]]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError):
        return {}
    scanner = _FlowScanner(
        singulars=set(singular_callees),
        plurals=set(plural_callees),
        overloaded=set(overloaded_callees),
        contextual_singulars=set(contextual_singular_callees),
        contextual_plurals=set(contextual_plural_callees),
    )
    return scanner.scan(tree)


def _flow_resolution(models: list[_FlowModel], count: int | None) -> _FlowResolution:
    active = []
    uncertain = []
    for model in models:
        reachable = _value_scalar(model.reachable, model.count_var, count)
        if reachable is True:
            active.append(model)
        elif reachable is None:
            uncertain.append(model)
    if uncertain:
        return _FlowResolution(Supplier("unknown", "none", reason="unresolved use reachability"),
                               tuple(sorted({model.use_line for model in active + uncertain})),
                               "unresolved count-path condition", None)
    if not active:
        return _FlowResolution(Supplier("none", "none"), (), "unreachable at this count", False)
    uses = [model for model in active if model.mode != "lookup"]
    if not uses:
        return _FlowResolution(Supplier("none", "none"), ())
    suppliers = [_supplier_from_value(model.value, model.mode, model.count_var, count) for model in uses]
    use_lines = tuple(sorted({model.use_line for model in uses}))
    if not suppliers:
        return _FlowResolution(Supplier("unknown", "none", reason="no recovered formatting use"), use_lines)
    if all(supplier == suppliers[0] for supplier in suppliers):
        return _FlowResolution(suppliers[0], use_lines)
    return _FlowResolution(
        Supplier("unknown", suppliers[0].mode, reason="multiple formatting uses have different supplier shapes"),
        use_lines,
        "multiple formatting uses",
    )


def _percent_requirement(code: str) -> str:
    if code in "diu":
        return "decimal"
    if code in "oxX":
        return "int"
    if code in "eEfFgG":
        return "number"
    if code == "c":
        return "char"
    return "any"


def _brace_requirement(spec: str, conversion: str | None) -> str:
    cleaned = re.sub(r"\{[^{}]+\}", "", spec)
    match = re.search(r"([bcdeEfFgGnosxX%])$", cleaned)
    if not match:
        return "any"
    code = match.group(1)
    if conversion in {"s", "r", "a"}:
        # Native conversion produces a string *before* applying the spec.
        return "any" if code == "s" else "invalid-converted-string-spec"
    if code in "bcdnosxX":
        return "int" if code != "s" else "str"
    if code in "eEfFgG%":
        return "number"
    return "any"


def _merge_requirement(existing: str | None, new: str) -> str:
    if existing is None or existing == "any":
        return new
    if new == "any" or new == existing:
        return existing
    if {existing, new} <= {"int", "decimal", "number"}:
        if "int" not in {existing, new}:
            return "decimal"
        return "int"
    if {existing, new} <= {"int", "char"}:
        return "int"
    return "mixed"


def pattern_requirements(pattern: str) -> PatternRequirements:
    percent_names: list[str] = []
    percent_positional = 0
    percent_named_types: dict[str, str] = {}
    percent_positional_types: list[str] = []
    consumed: list[tuple[int, int]] = []
    for match in _PERCENT.finditer(pattern):
        consumed.append(match.span())
        if "*" in match.group(0):
            return PatternRequirements("unknown", "percent", reason="dynamic width or precision is unsupported")
        code = match.group(2)
        if code == "%":
            continue
        requirement = _percent_requirement(code)
        if match.group(1) is None:
            percent_positional += 1
            percent_positional_types.append(requirement)
        else:
            name = match.group(1)
            percent_names.append(name)
            percent_named_types[name] = _merge_requirement(percent_named_types.get(name), requirement)

    masked = list(pattern)
    for start, end in consumed:
        masked[start:end] = " " * (end - start)
    if "%" in "".join(masked):
        return PatternRequirements("unknown", "percent", reason="unsupported or stray percent directive")

    brace_names: list[str] = []
    brace_positional = 0
    brace_named_types: dict[str, str] = {}
    brace_positional_types: list[str] = []
    brace_indices: dict[int, str] = {}
    auto_index = 0
    numbering: str | None = None
    brace_seen = False
    try:
        for _, field, spec, conversion in Formatter().parse(pattern):
            if field is None:
                continue
            brace_seen = True
            if conversion not in {None, "s", "r", "a"}:
                return PatternRequirements("unknown", "brace", reason="unsupported brace conversion")
            if "." in field or "[" in field:
                return PatternRequirements("unknown", "brace", reason="attribute or index traversal is unsupported")
            root = field.split(".", 1)[0].split("[", 1)[0]
            requirement = _brace_requirement(spec, conversion)
            if root == "" or root.isdigit():
                current_numbering = "auto" if root == "" else "manual"
                if numbering is not None and numbering != current_numbering:
                    return PatternRequirements("unknown", "brace", reason="mixed automatic and manual numbering")
                numbering = current_numbering
                index = auto_index if root == "" else int(root)
                auto_index += root == ""
                if index > 4096:
                    return PatternRequirements("unknown", "brace", reason="positional index exceeds local bound")
                brace_indices[index] = _merge_requirement(brace_indices.get(index), requirement)
                brace_positional = max(brace_positional, index + 1)
            elif re.fullmatch(r"[A-Za-z_]\w*", root):
                brace_names.append(root)
                brace_named_types[root] = _merge_requirement(brace_named_types.get(root), requirement)
            else:
                return PatternRequirements("unknown", "brace", reason="unsupported brace field")
            # Nested replacement fields in a format specification are names in
            # their own right.  Their concrete accepted type depends on the
            # surrounding mini-language, so they are retained with type ``any``.
            for _, nested, nested_spec, nested_conversion in Formatter().parse(spec):
                if nested is None:
                    continue
                if not re.fullmatch(r"[A-Za-z_]\w*", nested) or nested_spec or nested_conversion:
                    return PatternRequirements("unknown", "brace", reason="unsupported nested format field")
                brace_names.append(nested)
                brace_named_types[nested] = _merge_requirement(brace_named_types.get(nested), "any")
    except ValueError as exc:
        return PatternRequirements("unknown", "brace", reason=f"invalid brace format: {exc}")

    percent_seen = bool(consumed)
    if percent_seen and brace_seen:
        return PatternRequirements("unknown", "mixed", reason="mixed percent and brace formatting")
    if percent_seen:
        if "mixed" in percent_named_types.values():
            return PatternRequirements("unknown", "percent", reason="one named field has incompatible directives")
        return PatternRequirements(
            "known",
            "percent",
            tuple(sorted(set(percent_names))),
            percent_positional,
            named_types=tuple(sorted(percent_named_types.items())),
            positional_types=tuple(percent_positional_types),
        )
    if brace_seen:
        if "mixed" in brace_named_types.values() or "mixed" in brace_indices.values():
            return PatternRequirements("unknown", "brace", reason="one brace field has incompatible directives")
        return PatternRequirements(
            "known",
            "brace",
            tuple(sorted(set(brace_names))),
            brace_positional,
            named_types=tuple(sorted(brace_named_types.items())),
            positional_types=tuple(brace_indices.get(i, "any") for i in range(brace_positional)),
        )
    return PatternRequirements("known", "none")


def _compatible(requirement: str, supplied: str) -> bool | None:
    if requirement == "invalid-converted-string-spec":
        return False
    if supplied == "unknown":
        return None
    if requirement == "any":
        return True
    if requirement == "int":
        return supplied in {"int", "bool"}
    if requirement == "decimal":
        if supplied in {"float", "number"}:
            return None  # Finiteness is value-dependent for unresolved floats.
        return supplied in {"int", "bool", "finite-float"}
    if requirement == "number":
        return supplied in {"int", "float", "finite-float", "nonfinite-float", "number", "bool"}
    if requirement == "str":
        return supplied == "str"
    if requirement == "char":
        return None if supplied == "str" else supplied in {"int", "bool"}
    return None


def _qualification(requirements: PatternRequirements, supplier: Supplier) -> dict[str, Any]:
    result: dict[str, Any] = {
        "requirements": asdict(requirements),
        "supplier": asdict(supplier),
        "status": "clean",
        "missing": [],
        "type_mismatches": [],
        "type_unknown": [],
    }
    if requirements.status != "known":
        result.update(status="unknown", reason=requirements.reason)
        return result

    if requirements.dialect == "percent" and supplier.mode in {"str.format", "format_map"}:
        result.update(status="error", reason="percent pattern is passed to brace formatting")
        return result
    if requirements.dialect == "brace" and supplier.mode == "percent":
        result.update(status="error", reason="brace pattern is passed to percent formatting")
        return result
    if requirements.dialect in {"percent", "brace"} and supplier.mode == "call-keywords" and requirements.dialect != "percent":
        result.update(status="unknown", reason="new-style call keyword interpolation is only admitted for percent patterns")
        return result

    if supplier.status == "unknown":
        result.update(status="unknown", reason=supplier.reason)
        return result
    needs_any = bool(requirements.names or requirements.positional)
    if not needs_any:
        if supplier.status == "known" and supplier.positional and supplier.mode == "percent":
            result.update(status="error", reason="positional percent supplier but selected pattern has no directive")
        return result
    if supplier.status == "none":
        result.update(status="unknown", reason="selected pattern requires formatting but no supplier was recovered")
        return result

    if requirements.dialect == "percent" and supplier.mode == "percent" and supplier.is_mapping:
        if requirements.names and requirements.positional:
            result.update(status="unknown", reason="mixed keyed and unkeyed percent conversions")
            return result
        if not requirements.names:
            # A dict is one formatting object, not a tuple of its values.
            supplier = replace(supplier, names=(), positional=1, positional_types=("mapping",))

    missing = sorted(set(requirements.names) - set(supplier.names))
    positional_missing = max(0, requirements.positional - supplier.positional)
    result["missing"] = missing
    result["positional_missing"] = positional_missing
    if requirements.names and supplier.positional and not supplier.names:
        result.update(status="error", reason="named fields paired with positional supplier")
        return result
    if requirements.positional and supplier.names and not supplier.positional:
        result.update(status="error", reason="positional fields paired with named supplier")
        return result
    if missing or positional_missing:
        result.update(status="error", reason="selected pattern requests unsupplied formatting fields")
        return result
    if (requirements.dialect == "percent" and supplier.mode == "percent"
            and supplier.positional > requirements.positional):
        result.update(status="error", reason="unused positional percent arguments",
                      positional_extra=supplier.positional - requirements.positional)
        return result

    supplied_named = dict(supplier.named_types)
    for name, requirement in requirements.named_types:
        verdict = _compatible(requirement, supplied_named.get(name, "unknown"))
        if verdict is False:
            result["type_mismatches"].append(
                {"field": name, "required": requirement, "supplied": supplied_named.get(name, "unknown")}
            )
        elif verdict is None:
            result["type_unknown"].append(
                {"field": name, "required": requirement, "supplied": supplied_named.get(name, "unknown")}
            )
    for index, requirement in enumerate(requirements.positional_types):
        supplied = supplier.positional_types[index] if index < len(supplier.positional_types) else "unknown"
        verdict = _compatible(requirement, supplied)
        if verdict is False:
            result["type_mismatches"].append({"position": index, "required": requirement, "supplied": supplied})
        elif verdict is None:
            result["type_unknown"].append({"position": index, "required": requirement, "supplied": supplied})
    if result["type_mismatches"]:
        result.update(status="error", reason="selected pattern receives a definitely incompatible primitive type")
    elif result["type_unknown"]:
        result.update(status="unknown", reason="selected pattern type requirement cannot be proved from the local supplier")
    return result


def _runtime_observations(call: CallSite, runtime: CatalogRuntime, max_count: int) -> list[dict[str, Any]]:
    """Execute every bounded count; caller coalesces with supplier shapes.

    Coalescing on the locale branch alone is unsound for project qualification:
    a supplier may change at ``n == 100`` while the selected plural pattern is
    unchanged.  Runtime observations are cached per message/catalog, then each
    call site coalesces the product of runtime branch and recovered supplier.
    """
    if call.kind == "singular":
        runtime.reset()
        pattern = runtime.pgettext(call.context, call.singular or "") if call.context is not None else runtime.gettext(call.singular or "")
        return [{"count": None, "pattern": pattern, "lookup": runtime.serialize_trace()[-1]}]
    rows: list[dict[str, Any]] = []
    counts = [call.count_literal] if call.count_binding == "fixed" else range(max_count + 1)
    for count in counts:
        runtime.reset()
        if call.context is not None:
            pattern = runtime.npgettext(call.context, call.singular or "", call.plural or "", count)
        else:
            pattern = runtime.ngettext(call.singular or "", call.plural or "", count)
        rows.append({"count": count, "pattern": pattern, "lookup": runtime.serialize_trace()[-1]})
    return rows


def _compress_counts(counts: list[int | None]) -> list[list[int | None]]:
    if not counts:
        return []
    if counts == [None]:
        return [[None, None]]
    numeric = sorted({int(value) for value in counts if value is not None})
    ranges: list[list[int | None]] = []
    start = previous = numeric[0]
    for value in numeric[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append([start, previous])
        start = previous = value
    ranges.append([start, previous])
    return ranges


def audit_project(
    source_root: Path,
    catalogs: list[Path],
    *,
    max_count: int = 200,
    require_catalog: bool = False,
    max_files: int = 2000,
    singular_callees: Iterable[str] = ("gettext", "_"),
    plural_callees: Iterable[str] = ("ngettext",),
    overloaded_callees: Iterable[str] = (),
    contextual_singular_callees: Iterable[str] = ("pgettext",),
    contextual_plural_callees: Iterable[str] = ("npgettext",),
    analysis_mode: str = "flow",
) -> dict[str, Any]:
    if not 0 <= max_count <= 1000:
        raise ValueError("max_count must be in 0..1000")
    if analysis_mode not in {"direct", "flow"}:
        raise ValueError("analysis_mode must be direct or flow")
    source_root = source_root.resolve()
    files = [source_root] if source_root.is_file() else sorted(source_root.rglob("*.py"))
    if len(files) > max_files:
        raise ValueError(f"source file budget exceeded: {len(files)} > {max_files}")
    calls: list[CallSite] = []
    flow_models: dict[tuple[str, int, int], list[_FlowModel]] = {}
    for path in files:
        try:
            rel = str(path.resolve().relative_to(source_root)) if source_root.is_dir() else path.name
            source = path.read_text(encoding="utf-8")
            calls.extend(
                scan_source(
                    source,
                    rel,
                    singular_callees=singular_callees,
                    plural_callees=plural_callees,
                    overloaded_callees=overloaded_callees,
                    contextual_singular_callees=contextual_singular_callees,
                    contextual_plural_callees=contextual_plural_callees,
                )
            )
            if analysis_mode == "flow":
                recovered = _recover_flow_models(
                    source,
                    singular_callees=singular_callees,
                    plural_callees=plural_callees,
                    overloaded_callees=overloaded_callees,
                    contextual_singular_callees=contextual_singular_callees,
                    contextual_plural_callees=contextual_plural_callees,
                )
                for (line, column), models in recovered.items():
                    flow_models[(rel, line, column)] = models
        except (OSError, UnicodeError) as exc:
            calls.append(
                CallSite(
                    str(path),
                    0,
                    0,
                    "",
                    "unknown",
                    None,
                    None,
                    Supplier("unknown", "none", reason="read failure"),
                    "unknown",
                    f"read: {exc}",
                )
            )

    runtimes: list[tuple[Path, CatalogRuntime | None, str | None]] = []
    for catalog in sorted(dict.fromkeys(path.resolve() for path in catalogs)):
        try:
            runtimes.append((catalog, CatalogRuntime(catalog), None))
        except (OSError, ValueError, SyntaxError) as exc:
            runtimes.append((catalog, None, str(exc)))

    findings: list[dict[str, Any]] = []
    witness_cache: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    cache_hits = 0
    flow_witnesses = 0
    flow_calls: set[tuple[str, int, int]] = set()
    type_errors = 0
    type_unknowns = 0
    for call in calls:
        if call.status != "literal":
            findings.append({"call": asdict(call), "catalog": None, "status": "unknown", "reason": call.reason})
            continue
        if call.kind == "plural" and (
            call.count_binding == "unknown"
            or (call.count_binding == "fixed" and not 0 <= call.count_literal <= max_count)
        ):
            findings.append({"call": asdict(call), "catalog": None, "status": "unknown",
                             "reason": "plural selector is outside the admitted count binding"})
            continue
        if not runtimes:
            findings.append({"call": asdict(call), "catalog": None, "status": "unknown", "reason": "no catalog supplied"})
            continue
        model_key = (call.path, call.line, call.column)
        models = flow_models.get(model_key, []) if analysis_mode == "flow" else []
        for path, runtime, error in runtimes:
            if runtime is None:
                findings.append(
                    {
                        "call": asdict(call),
                        "catalog": str(path),
                        "status": "unknown",
                        "reason": f"catalog unavailable: {error}",
                    }
                )
                continue
            witnesses = []
            statuses: list[str] = []
            cache_key = (str(path), call.kind, call.context, call.singular, call.plural,
                         max_count, call.count_binding, call.count_literal)
            if cache_key in witness_cache:
                base_witnesses = witness_cache[cache_key]
                cache_hits += 1
            else:
                base_witnesses = _runtime_observations(call, runtime, max_count)
                witness_cache[cache_key] = base_witnesses
            selected: list[tuple[dict[str, Any], Supplier, dict[str, Any] | None, list[int | None]]] = []
            selected_products: dict[str, int] = {}
            unreachable_counts: list[int | None] = []
            for observation in base_witnesses:
                effective_supplier = call.supplier
                flow_meta: dict[str, Any] | None = None
                if models:
                    resolution = _flow_resolution(models, observation["count"])
                    if resolution.reachable is False:
                        unreachable_counts.append(observation["count"])
                        continue
                    effective_supplier = resolution.supplier
                    flow_meta = {
                        "use_lines": resolution.use_lines,
                        "reason": resolution.reason,
                        "supplier": asdict(resolution.supplier),
                        "reachable": resolution.reachable,
                    }
                product_key = json.dumps(
                    {
                        "branch": observation["lookup"]["branch"],
                        "resolution": observation["lookup"]["resolution"],
                        "pattern": observation["pattern"],
                        "supplier": asdict(effective_supplier),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
                if product_key in selected_products:
                    selected[selected_products[product_key]][3].append(observation["count"])
                    continue
                selected_products[product_key] = len(selected)
                selected.append((observation, effective_supplier, flow_meta, [observation["count"]]))

            for witness, effective_supplier, flow_meta, covered_counts in selected:
                if models:
                    flow_calls.add(model_key)
                    flow_witnesses += 1
                qualification = _qualification(pattern_requirements(witness["pattern"]), effective_supplier)
                fallback = witness["lookup"]["resolution"] in (
                    "source-fallback",
                    "compiler-source-substitution",
                )
                if require_catalog and fallback and (flow_meta is None or flow_meta["reachable"] is True):
                    previous = qualification["status"]
                    qualification["format_status_before_presence_check"] = previous
                    qualification.update(status="error", reason="catalog-presence obligation violated")
                if qualification.get("type_mismatches"):
                    type_errors += 1
                if qualification.get("type_unknown"):
                    type_unknowns += 1
                statuses.append(qualification["status"])
                witnesses.append(
                    {
                        **witness,
                        "qualification": qualification,
                        "effective_supplier": asdict(effective_supplier),
                        "flow": flow_meta,
                        "fallback": fallback,
                        "covered_count_ranges": _compress_counts(covered_counts),
                        "covered_count_total": len(covered_counts),
                    }
                )
            status = "error" if "error" in statuses else ("unknown" if "unknown" in statuses or not statuses else "clean")
            findings.append(
                {
                    "call": asdict(call),
                    "catalog": str(path),
                    "babel_checks": runtime.checks,
                    "witnesses": witnesses,
                    "status": status,
                    "unreachable_count_ranges": _compress_counts(unreachable_counts),
                    "reason": "no reachable boundary in the declared domain" if not statuses else None,
                }
            )

    summary = {
        "source_root": str(source_root),
        "analysis_mode": analysis_mode,
        "python_files": len(files),
        "calls": len(calls),
        "literal_calls": sum(call.status == "literal" for call in calls),
        "catalogs": len(runtimes),
        "findings": len(findings),
        "clean": sum(finding["status"] == "clean" for finding in findings),
        "errors": sum(finding["status"] == "error" for finding in findings),
        "unknown": sum(finding["status"] == "unknown" for finding in findings),
        "selected_patterns": sum(len(finding.get("witnesses", [])) for finding in findings),
        "runtime_observations": sum(len(values) for values in witness_cache.values()),
        "unique_runtime_lookup_sets": len(witness_cache),
        "runtime_lookup_cache_hits": cache_hits,
        "flow_models": sum(len(models) for models in flow_models.values()),
        "flow_recovered_calls": len(flow_calls),
        "flow_resolved_witnesses": flow_witnesses,
        "type_error_witnesses": type_errors,
        "type_unknown_witnesses": type_unknowns,
    }
    return {
        "summary": summary,
        "findings": findings,
        "assumptions": [
            "configured callee names/attributes are treated as caller-verified gettext bindings",
            "source files are parsed and never imported or executed",
            "flow recovery is intraprocedural and bounded to local def-use, simple branches, and primitive types",
            "unresolved branch conditions, heap values, indirect calls, and cross-function flows remain unknown",
            "catalog selection is delegated to Babel MO compilation and Python GNUTranslations",
            "results qualify formatting and catalog-presence obligations, not linguistic correctness",
        ],
    }


def _catalog_paths(values: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        if value.is_dir():
            paths.extend(sorted(value.rglob("*.po")))
        else:
            paths.append(value)
    return paths


def _write_pytest_guard(path: Path, source: Path, catalogs: list[Path],
                        args: argparse.Namespace, report: dict[str, Any]) -> None:
    fields = ("path", "line", "column", "callee", "kind", "singular", "plural", "context")
    expected = [tuple(finding["call"][field] for field in fields) + (finding["catalog"],)
                for finding in report["findings"] if finding.get("catalog") is not None]
    if not expected or not report["summary"]["literal_calls"]:
        raise ValueError("cannot emit a guard without recognized call/catalog boundaries")
    source_literal = repr(str(source.resolve()))
    catalog_literal = repr([str(item.resolve()) for item in catalogs])
    text = f'''"""Generated analyzer requalification guard; review paths and boundary identities.

This statically re-audits configured boundaries; it does not execute target code.
Regenerate after an intentional boundary move/removal or configuration change.
"""
from pathlib import Path

from msgbranch.project import audit_project


def test_localized_message_boundaries():
    report = audit_project(
        Path({source_literal}),
        [Path(value) for value in {catalog_literal}],
        max_count={args.max_count},
        require_catalog={args.require_catalog!r},
        analysis_mode={args.analysis_mode!r},
        singular_callees={args.singular_callee!r},
        plural_callees={args.plural_callee!r},
        contextual_singular_callees={args.contextual_singular_callee!r},
        contextual_plural_callees={args.contextual_plural_callee!r},
        overloaded_callees={args.overloaded_callee!r},
    )
    fields = {fields!r}
    expected = set({expected!r})
    actual = {{tuple(finding["call"][field] for field in fields) + (finding["catalog"],)
              for finding in report["findings"]}}
    assert expected and expected <= actual, ("boundary recognition lost", expected - actual, report)
    assert report["summary"]["literal_calls"] > 0, report
    assert report["summary"]["selected_patterns"] > 0, report
    assert report["summary"]["errors"] == 0, report
    assert report["summary"]["unknown"] == 0, report
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Python source file or project root")
    parser.add_argument("catalog", nargs="+", type=Path, help="PO file or directory; directories are recursive")
    parser.add_argument("--max-count", type=int, default=200)
    parser.add_argument("--require-catalog", action="store_true")
    parser.add_argument("--analysis-mode", choices=("direct", "flow"), default="flow")
    parser.add_argument("--singular-callee", action="append", default=["gettext", "_"], help="repeatable literal singular wrapper name")
    parser.add_argument("--plural-callee", action="append", default=["ngettext"], help="repeatable literal plural wrapper name")
    parser.add_argument("--contextual-singular-callee", action="append", default=["pgettext"], help="repeatable contextual singular wrapper name")
    parser.add_argument("--contextual-plural-callee", action="append", default=["npgettext"], help="repeatable contextual plural wrapper name")
    parser.add_argument("--overloaded-callee", action="append", default=[], help="repeatable wrapper: one argument is singular, three are plural")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit-pytest", type=Path, help="write a reviewable pytest CI guard for these paths")
    args = parser.parse_args()
    catalogs = _catalog_paths(args.catalog)
    try:
        report = audit_project(
            args.source,
            catalogs,
            max_count=args.max_count,
            require_catalog=args.require_catalog,
            singular_callees=args.singular_callee,
            plural_callees=args.plural_callee,
            overloaded_callees=args.overloaded_callee,
            contextual_singular_callees=args.contextual_singular_callee,
            contextual_plural_callees=args.contextual_plural_callee,
            analysis_mode=args.analysis_mode,
        )
        code = 1 if report["summary"]["errors"] else (2 if report["summary"]["unknown"] else 0)
        if args.emit_pytest:
            _write_pytest_guard(args.emit_pytest, args.source, catalogs, args, report)
    except (OSError, ValueError) as exc:
        report, code = {"status": "unavailable-or-unknown", "error": str(exc)}, 2
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
