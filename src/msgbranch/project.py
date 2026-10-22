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
import sys
from typing import Any, Iterable, Mapping

from .runtime import CatalogRuntime
from .program import Unsupported

_MAX_SOURCE_BYTES = 1_000_000
_MAX_AST_NODES = 40_000

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
class _ConversionValue:
    name: str
    value: Any


@dataclass(frozen=True)
class _BinaryValue:
    operator: type
    left: Any
    right: Any


@dataclass(frozen=True)
class _PredicateValue:
    values: tuple[Any, ...]
    operators: tuple[type, ...]


@dataclass(frozen=True)
class _MappingValue:
    items: tuple[tuple[str, Any], ...]
    unknown_keys: bool = False
    reason: str | None = None
    all_constructed_items_closed: bool = True
    constructed_values: tuple[Any, ...] = ()


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
        return "str" if all(isinstance(x, ast.Constant) and type(x.value) is str for x in node.values) else "unknown"
    if isinstance(node, ast.Compare):
        if all(isinstance(x, ast.Constant) for x in [node.left, *node.comparators]):
            return "bool" if _condition(node, {}, None, None) is not None else "unknown"
        return "unknown"
    if isinstance(node, ast.BoolOp):
        return "unknown"  # and/or return operands, not necessarily bools.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {"float", "str", "int", "bool"}:
            if len(node.args) == 1 and not node.keywords:
                return _conversion_type(node.func.id, _literal_supplier_type(node.args[0]))
            return "unknown"
        if node.func.id == "len" and len(node.args) == 1 and not node.keywords:
            try:
                # literal_eval constructs literals only, never arbitrary calls
                # or arithmetic. It also visits overwritten dictionary values.
                value = ast.literal_eval(node.args[0])
            except (TypeError, ValueError, SyntaxError):
                return "unknown"
            if type(value) in {str, tuple, list, dict, set, bytes}:
                return _integer_supplier_type(len(value))
        return "unknown"
    return "unknown"


def _integer_supplier_type(value: int) -> str:
    if 0 <= value <= 4096:
        return "bounded-nonnegative-int"
    if 0 <= value <= 0x10FFFF:
        return "unicode-codepoint-int"
    digit_limit = sys.get_int_max_str_digits()
    if digit_limit and abs(value) >= 10 ** digit_limit:
        return "decimal-overflow-int"
    # Integer presentation has no float range limit. Floating presentation
    # converts first; preserve that separate range fact in the abstraction.
    try:
        float(value)
    except OverflowError:
        return "float-overflow-int"
    return "finite-float-int"


def _float_conversion_type(supplied: str) -> str:
    # A float-producing call is not evidence that its argument can be coerced.
    # In particular an unbounded or overflow-sized integer may raise first.
    if supplied in {"bounded-nonnegative-int", "unicode-codepoint-int", "finite-float-int",
                    "float", "finite-float", "nonfinite-float", "bool"}:
        return "float"
    return "unknown"


def _conversion_type(name: str, supplied: str) -> str:
    if name in {"bool", "not"}:
        # Preserve the argument's qualification rather than erasing a failed
        # or unresolved computation behind the constructor's result type.
        if supplied in {"bounded-nonnegative-int", "unicode-codepoint-int",
                       "finite-float-int", "float-overflow-int", "decimal-overflow-int",
                       "float", "finite-float", "nonfinite-float", "str", "bool", "none"}:
            return "bool"
        return "unknown"
    if name == "float":
        return _float_conversion_type(supplied)
    integers = {"int", "bounded-nonnegative-int", "unicode-codepoint-int",
                "finite-float-int", "float-overflow-int", "decimal-overflow-int"}
    if name == "int":
        if supplied in integers:
            return supplied
        if supplied == "bool":
            return "bounded-nonnegative-int"
        if supplied == "finite-float":
            return "finite-float-int"
        return "unknown"
    if name == "str":
        if supplied == "decimal-overflow-int" or (supplied == "int" and sys.get_int_max_str_digits()):
            return "unknown"
        if supplied in integers | {"str", "bool", "none", "float", "finite-float", "nonfinite-float"}:
            return "str"
    return "unknown"


def _literal_supplier_type(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return _integer_supplier_type(node.value)
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int):
        value = node.operand.value
        return _integer_supplier_type(-value if isinstance(node.op, ast.USub) else value)
    return _primitive_type(node)


def _mapping_supplier(node: ast.AST, mode: str) -> Supplier:
    if isinstance(node, ast.Dict):
        types: dict[str, str] = {}
        for key, value_node in zip(node.keys, node.values, strict=True):
            if key is None:
                return Supplier("unknown", mode, reason="mapping expansion")
            value = _literal_string(key)
            if value is None:
                return Supplier("unknown", mode, reason="dynamic mapping key")
            if value in types and types[value] == "unknown":
                return Supplier("unknown", mode, reason="overwritten mapping value construction is not qualified")
            types[value] = _literal_supplier_type(value_node)
        return Supplier("known", mode, tuple(sorted(types)), named_types=tuple(sorted(types.items())), is_mapping=True)
    if isinstance(node, ast.List):
        return Supplier("unknown", mode, reason="percent list supplier is not a positional tuple")
    if isinstance(node, ast.Tuple):
        if any(isinstance(x, ast.Starred) for x in node.elts):
            return Supplier("unknown", mode, reason="positional expansion")
        return Supplier(
            "known",
            mode,
            positional=len(node.elts),
            positional_types=tuple(_literal_supplier_type(x) for x in node.elts),
        )
    if isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.IfExp)):
        return Supplier("unknown", mode, reason="dynamic formatting supplier")
    return Supplier("known", mode, positional=1, positional_types=(_literal_supplier_type(node),))


def _format_supplier(node: ast.Call) -> Supplier:
    if any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords):
        return Supplier("unknown", "str.format", reason="argument expansion")
    names = tuple(sorted(k.arg for k in node.keywords if k.arg is not None))
    return Supplier(
        "known",
        "str.format",
        names,
        len(node.args),
        named_types=tuple(sorted((k.arg, _literal_supplier_type(k.value)) for k in node.keywords if k.arg is not None)),
        positional_types=tuple(_literal_supplier_type(x) for x in node.args),
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
            named_types=tuple(sorted((k.arg, _literal_supplier_type(k.value)) for k in call.keywords if k.arg is not None)),
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


def _analysis_diagnostic(path: str, exc: Exception) -> CallSite:
    reason = f"analysis: {type(exc).__name__}: {exc}"
    return CallSite(path, getattr(exc, "lineno", 0) or 0, 0, "", "unknown", None, None,
                    Supplier("unknown", "none", reason=reason), "unknown", reason)


def _preflight(source: str, path: str) -> tuple[ast.Module, list[ast.AST]]:
    """Admit one parsed tree for both syntax and flow; rejection has no retry."""
    if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise Unsupported("source exceeds 1 MB budget")
    tree = ast.parse(source, filename=path)
    nodes = []
    for node in ast.walk(tree):
        if len(nodes) >= _MAX_AST_NODES:
            raise Unsupported("AST exceeds 40,000-node budget")
        nodes.append(node)
    return tree, nodes


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
    try:
        _, nodes = _preflight(source, path)
        return _scan_nodes(
            nodes, path, singular_callees=singular_callees, plural_callees=plural_callees,
            overloaded_callees=overloaded_callees,
            contextual_singular_callees=contextual_singular_callees,
            contextual_plural_callees=contextual_plural_callees,
        )
    except (SyntaxError, Unsupported, RecursionError, MemoryError) as exc:
        return [_analysis_diagnostic(path, exc)]


def _scan_nodes(
    nodes: list[ast.AST], path: str, *,
    singular_callees: Iterable[str], plural_callees: Iterable[str],
    overloaded_callees: Iterable[str], contextual_singular_callees: Iterable[str],
    contextual_plural_callees: Iterable[str],
) -> list[CallSite]:
    parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
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


def _closed_literal_value(value: Any) -> bool:
    """Whether constructing an owned primitive/container needs no unresolved evaluation."""
    if isinstance(value, _Primitive):
        return value.has_literal and type(value.literal) in {str, int, float, bool, type(None)}
    if isinstance(value, _SequenceValue):
        return not value.unknown_items and all(_closed_literal_value(item) for item in value.items)
    if isinstance(value, _MappingValue):
        return (not value.unknown_keys and value.all_constructed_items_closed
                and all(_closed_literal_value(item) for _, item in value.items))
    return False


def _literal_container_length(value: Any) -> int | None:
    if not _closed_literal_value(value):
        return None
    if isinstance(value, _Primitive) and type(value.literal) is str:
        return len(value.literal)
    if isinstance(value, (_SequenceValue, _MappingValue)):
        return len(value.items)
    return None


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
                # An augmented update may mutate the old object, not merely
                # rebind the target name. Do not retain its aliases as facts.
                self._invalidate_container(statement.target, env, "unsupported augmented container assignment")
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
                before = dict(env)
                body_env, else_env = dict(before), dict(before)
                self.reachable = _Unknown("unsupported loop reachability")
                if not isinstance(statement, ast.While):
                    self._bind(statement.target, _Unknown("loop iteration value"), body_env)
                self._block(statement.body, body_env)
                self.reachable = _Unknown("unsupported loop reachability")
                self._block(statement.orelse, else_env)
                # Neither iteration count nor break/else termination is modeled.
                # Preserve effects from both branches, including terminated ones,
                # and do not certify a later use as unconditionally reachable.
                self.reachable = _Unknown("unsupported loop reachability")
                for name in set(before) | set(body_env) | set(else_env):
                    if body_env.get(name) != before.get(name) or else_env.get(name) != before.get(name):
                        if isinstance(before.get(name), _MessageValue):
                            self._record(before[name], "unknown", _Unknown("loop-dependent message binding"), statement)
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
        elif isinstance(target, (ast.Tuple, ast.List)):
            if self._exact_unpack(target, value):
                for child, item in zip(target.elts, value.items, strict=True):
                    self._bind(child, item, env)
            else:
                # Unknown RHS, expansion or nested arity mismatch must not
                # preserve any pre-assignment supplier binding.
                for child in target.elts:
                    self._bind(child, _Unknown("unresolved unpack assignment"), env)
        elif isinstance(target, ast.Starred):
            self._bind(target.value, _Unknown("starred assignment"), env)
        elif isinstance(target, (ast.Subscript, ast.Attribute)):
            self._expr(target, env)
            self._invalidate_container(target, env, "unsupported container assignment")

    def _exact_unpack(self, target: ast.AST, value: Any) -> bool:
        if isinstance(target, (ast.Tuple, ast.List)):
            return (isinstance(value, _SequenceValue) and not value.unknown_items
                    and len(target.elts) == len(value.items)
                    and all(self._exact_unpack(child, item)
                            for child, item in zip(target.elts, value.items, strict=True)))
        return isinstance(target, (ast.Name, ast.Subscript, ast.Attribute))

    def _invalidate_container(self, node: ast.AST, env: dict[str, Any], reason: str) -> None:
        while isinstance(node, (ast.Subscript, ast.Attribute)):
            node = node.value
        if not isinstance(node, ast.Name):
            return
        target = env.get(node.id)
        if not isinstance(target, (_MappingValue, _SequenceValue, _ConditionalValue)):
            return
        # An escaped outer container can expose mutable descendants. Include
        # those objects, then invalidate every binding containing any of them.
        affected = {id(target)}
        pending = [target]
        visited: set[int] = set()
        while pending:
            value = pending.pop()
            if id(value) in visited:
                continue
            visited.add(id(value))
            if isinstance(value, _MappingValue):
                affected.add(id(value))
                pending.extend(item for _, item in value.items)
            elif isinstance(value, _SequenceValue):
                if not value.is_tuple:
                    affected.add(id(value))
                pending.extend(value.items)
            elif isinstance(value, _ConditionalValue):
                pending.extend((value.when_true, value.when_false))
        def contains(value: Any) -> bool:
            if id(value) in affected:
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
            formatted = False
            for child in node.values:
                if isinstance(child, ast.FormattedValue):
                    formatted = True
                    self._expr(child.value, env)
                    self._expr(child.format_spec, env)
            # Both expression evaluation and the format specification may
            # raise, even when the eventual result would have type str.
            if formatted:
                return _Unknown("formatted-string construction is not qualified")
            return _Primitive("str", "".join(x.value for x in node.values), True)
        if isinstance(node, ast.Dict):
            items: dict[str, Any] = {}
            constructed = []
            reason = None
            all_items_closed = True
            for key, value in zip(node.keys, node.values, strict=True):
                self._expr(key, env)
                item = self._expr(value, env)
                constructed.append(item)
                # Overwritten values are still evaluated by Python. A later
                # duplicate key must not erase a failed/unknown construction.
                all_items_closed = all_items_closed and _closed_literal_value(item)
                literal = _literal_string(key)
                if key is None or literal is None:
                    reason = "mapping expansion or dynamic mapping key"
                else:
                    items[literal] = item
            return _MappingValue(tuple(items.items()), reason is not None, reason,
                                 all_items_closed, tuple(constructed))
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
                return _ConversionValue("not", operand)
            if (isinstance(operand, _Primitive) and operand.has_literal
                    and type(operand.literal) in {int, float}
                    and isinstance(node.op, (ast.USub, ast.UAdd))):
                literal = -operand.literal if isinstance(node.op, ast.USub) else +operand.literal
                return _Primitive(operand.type_name, literal, True)
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
            values = tuple(self._expr(child, env) for child in [node.left, *node.comparators])
            return _PredicateValue(values, tuple(type(op) for op in node.ops))
        if isinstance(node, ast.BinOp):
            left = self._expr(node.left, env)
            right = self._expr(node.right, env)
            if isinstance(node.op, ast.Mod) and isinstance(left, _MessageValue):
                self._record(left, "percent", right, node)
                return _Primitive("str")
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Div, ast.Pow)):
                # A result type alone cannot discharge evaluation preconditions
                # (e.g. n // (n - 100)). Keep operands until count qualification.
                value = _BinaryValue(type(node.op), left, right)
                literal = _value_scalar(value, None, None)
                if literal is not None:
                    return _Primitive(_primitive_type(ast.Constant(literal)), literal, True)
                return value
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
                        binding = env.get(count_node.id)
                        count_var = (binding.symbol if isinstance(binding, _Primitive) and binding.symbol is not None
                                     else f"count:{node.lineno}:{node.col_offset}")
                        # A later lookup of a reassigned name must not revive the
                        # symbol used by an earlier message's selector.
                        if not isinstance(binding, _Primitive) or not binding.has_literal:
                            env[count_node.id] = _Primitive("int", symbol=count_var)
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
                    if node.func.id == "bool":
                        size = _literal_container_length(arguments[0])
                        if size is not None:
                            return _Primitive("bool", bool(size), True)
                    # Retain the argument until a witness supplies an actual
                    # selector count; an annotation alone is still unbounded.
                    return _ConversionValue(node.func.id, arguments[0])
                if node.func.id == "len" and len(node.args) == 1 and not node.keywords:
                    size = _literal_container_length(arguments[0])
                    if size is not None:
                        return _Primitive("int", size, True)
                    return _Unknown("len argument is not a proven sized literal")
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


def _binary_scalar(kind: type, left: Any, right: Any) -> Any:
    """Evaluate owned primitive abstractions only, with bounded materialization."""
    if kind is ast.Add and type(left) is type(right) is str:
        return left + right if len(left) + len(right) <= 100_000 else None
    if type(left) not in {int, float, bool} or type(right) not in {int, float, bool}:
        return None
    if any(type(v) is int and abs(v).bit_length() > 4096 for v in (left, right)):
        return None
    try:
        if kind is ast.Add:
            value = left + right
        elif kind is ast.Sub:
            value = left - right
        elif kind is ast.Mult:
            value = left * right
        elif kind is ast.FloorDiv:
            value = left // right
        elif kind is ast.Div:
            value = left / right
        elif kind is ast.Pow:
            # Keep the existing integer-power admission and evaluation budget.
            if type(left) is not int or type(right) is not int or abs(right) > 4096:
                return None
            if right >= 0 and abs(left).bit_length() * right > 4096:
                return None
            value = left ** right
        else:
            return None
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None
    if type(value) is int and abs(value).bit_length() > 4096:
        return None
    return value


def _value_scalar(value: Any, count_var: str | None, count: int | None) -> Any:
    if isinstance(value, _BinaryValue):
        return _binary_scalar(value.operator, _value_scalar(value.left, count_var, count),
                              _value_scalar(value.right, count_var, count))
    if isinstance(value, _PredicateValue):
        current = _value_scalar(value.values[0], count_var, count)
        if current is None:
            return None
        for kind, argument in zip(value.operators, value.values[1:], strict=True):
            right = _value_scalar(argument, count_var, count)
            if right is None:
                return None
            try:
                if kind is ast.Eq: result = current == right
                elif kind is ast.NotEq: result = current != right
                elif kind is ast.Lt: result = current < right
                elif kind is ast.LtE: result = current <= right
                elif kind is ast.Gt: result = current > right
                elif kind is ast.GtE: result = current >= right
                elif kind is ast.Is: result = current is right
                elif kind is ast.IsNot: result = current is not right
                else: return None
            except TypeError:
                return None
            if not result:
                return False
            current = right
        return True
    if isinstance(value, _ConversionValue):
        argument = _value_scalar(value.value, count_var, count)
        if type(argument) not in (int, float, str, bool):
            return None
        try:
            return {"str": str, "int": int, "float": float, "bool": bool,
                    "not": lambda x: not x}[value.name](argument)
        except (TypeError, ValueError, OverflowError):
            return None
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
        except (TypeError, ValueError, OverflowError):
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
    if isinstance(value, _BinaryValue):
        literal = _value_scalar(value, count_var, count)
        if literal is not None:
            return _literal_supplier_type(ast.Constant(literal))
        left = _abstract_type(value.left, count_var, count)
        right = _abstract_type(value.right, count_var, count)
        integers = {"int", "bool", "bounded-nonnegative-int", "unicode-codepoint-int",
                    "finite-float-int", "float-overflow-int", "decimal-overflow-int"}
        if value.operator is ast.Add and left == right == "str":
            return "str"
        if left in integers and right in integers:
            if value.operator in {ast.Add, ast.Sub, ast.Mult, ast.FloorDiv}:
                return "int"
            exponent = _value_scalar(value.right, count_var, count)
            if value.operator is ast.Pow and type(exponent) is int and exponent >= 0:
                return "int"
        floats = {"float", "finite-float", "nonfinite-float"}
        if value.operator is not ast.Pow and left in floats and right in floats:
            return "float"
        return "unknown"
    if isinstance(value, _PredicateValue):
        return "bool" if _value_scalar(value, count_var, count) is not None else "unknown"
    if isinstance(value, _ConversionValue):
        return _conversion_type(value.name, _abstract_type(value.value, count_var, count))
    if isinstance(value, _Primitive):
        if count_var is not None and value.symbol == count_var and count is not None:
            return _integer_supplier_type(count)
        if value.has_literal and type(value.literal) is int:
            return _integer_supplier_type(value.literal)
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


def _construction_qualified(value: Any, count_var: str | None, count: int | None) -> bool:
    """Check evaluation obligations independently of a mapping's last-write view."""
    if _closed_literal_value(value):
        return True
    if isinstance(value, _Primitive):
        # A bound primitive or selector witness is an input, not evidence that
        # an unresolved arithmetic expression producing its type succeeded.
        return value.symbol is not None and _abstract_type(value, count_var, count) != "unknown"
    if isinstance(value, _ConversionValue):
        return (_construction_qualified(value.value, count_var, count)
                and _abstract_type(value, count_var, count) != "unknown")
    if isinstance(value, _PredicateValue):
        return _value_scalar(value, count_var, count) is not None
    if isinstance(value, _BinaryValue):
        if not (_construction_qualified(value.left, count_var, count)
                and _construction_qualified(value.right, count_var, count)):
            return False
        if _value_scalar(value, count_var, count) is not None:
            return True
        integers = {"int", "bool", "bounded-nonnegative-int", "unicode-codepoint-int",
                    "finite-float-int", "float-overflow-int", "decimal-overflow-int"}
        left = _abstract_type(value.left, count_var, count)
        right = _abstract_type(value.right, count_var, count)
        if value.operator is ast.Add and left == right == "str":
            return True
        if left in integers and right in integers:
            if value.operator in {ast.Add, ast.Sub, ast.Mult}:
                return True
            divisor = _value_scalar(value.right, count_var, count)
            if value.operator is ast.FloorDiv:
                return divisor is not None and divisor != 0
            if value.operator is ast.Pow:
                return type(divisor) is int and divisor >= 0
        return False
    if isinstance(value, _SequenceValue):
        return (not value.unknown_items
                and all(_construction_qualified(item, count_var, count) for item in value.items))
    if isinstance(value, _MappingValue):
        return (not value.unknown_keys and
                all(_construction_qualified(item, count_var, count)
                    for item in value.constructed_values or tuple(item for _, item in value.items)))
    if isinstance(value, _FormatArgsValue):
        return (not value.expanded
                and all(_construction_qualified(item, count_var, count)
                        for item in (*value.positional, *(item for _, item in value.keywords))))
    if isinstance(value, _ConditionalValue):
        branch = _condition(value.test, _env_dict(value.env), count_var, count)
        alternatives = ((value.when_true,) if branch is True else (value.when_false,)
                        if branch is False else (value.when_true, value.when_false))
        return all(_construction_qualified(item, count_var, count) for item in alternatives)
    return False


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
        if not _construction_qualified(value, count_var, count):
            return Supplier("unknown", mode, reason="mapping value construction is not qualified")
        names = tuple(sorted({name for name, _ in value.items}))
        types = tuple(sorted((name, _abstract_type(item, count_var, count)) for name, item in value.items))
        return Supplier("known", mode, names, named_types=types, is_mapping=True)
    if isinstance(value, _SequenceValue):
        if mode == "percent" and not value.is_tuple:
            return Supplier("unknown", mode, reason="percent list supplier is not a positional tuple")
        if value.unknown_items:
            return Supplier("unknown", mode, reason="positional expansion")
        if not _construction_qualified(value, count_var, count):
            return Supplier("unknown", mode, reason="positional value construction is not qualified")
        types = tuple(_abstract_type(item, count_var, count) for item in value.items)
        return Supplier("known", mode, positional=len(value.items), positional_types=types)
    if isinstance(value, _FormatArgsValue):
        if value.expanded:
            return Supplier("unknown", mode, reason="format argument expansion")
        if not _construction_qualified(value, count_var, count):
            return Supplier("unknown", mode, reason="format argument construction is not qualified")
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
    if isinstance(value, (_Primitive, _ConversionValue, _PredicateValue, _BinaryValue)):
        if not _construction_qualified(value, count_var, count):
            return Supplier("unknown", mode, reason="supplier value construction is not qualified")
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
    tree: ast.Module,
    *,
    singular_callees: Iterable[str],
    plural_callees: Iterable[str],
    overloaded_callees: Iterable[str],
    contextual_singular_callees: Iterable[str],
    contextual_plural_callees: Iterable[str],
) -> dict[tuple[int, int], list[_FlowModel]]:
    # Only the caller's admitted tree enters recovery. Exceptions propagate to
    # the per-file diagnostic, never an empty-model/direct-syntax fallback.
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
        return "float-number"
    if code == "c":
        return "char"
    return "stringable"


def _brace_requirement(spec: str, conversion: str | None) -> str | None:
    if not spec:
        return "stringable"
    # Admit a bounded mini-language, not an arbitrary prefix ending in a
    # familiar type code. Nested width/precision fields are checked separately.
    match = re.fullmatch(
        r"(?:(?P<fill>[^{}])?(?P<align>[<>=^]))?"
        r"(?P<sign>[+\- ])?(?P<alternate>#)?(?P<zero>0)?"
        r"(?P<width>[0-9]+|\{[A-Za-z_]\w*\})?(?P<grouping>[_,])?"
        r"(?:\.(?P<precision>[0-9]+|\{[A-Za-z_]\w*\}))?"
        r"(?P<code>[bcdeEfFgGnosxX%])?", spec,
    )
    if not match:
        return None
    code = match.group("code")
    if code is None:
        # Nonempty alignment/width requires a formatting implementation;
        # object.__format__ accepts only the empty spec (e.g. None). Explicit
        # string conversion happens before presentation and changes this case.
        if (match.group("align") == "=" or any(match.group(name) is not None
                for name in ("sign", "alternate", "grouping", "precision"))):
            return None
        return "stringable" if conversion in {"s", "r", "a"} else "formattable"
    if code in "bcdnosxX" and match.group("precision") is not None and code != "s":
        return None
    if code == "n" and match.group("grouping") is not None:
        return None
    if code in "cs" and (match.group("align") == "=" or any(match.group(name) is not None
            for name in ("sign", "alternate", "grouping"))):
        return None
    if code in "boxX" and match.group("grouping") == ",":
        return None
    if conversion in {"s", "r", "a"}:
        # Native conversion produces a string *before* applying the spec.
        return "stringable" if code == "s" else "invalid-converted-string-spec"
    if code == "c":
        return "codepoint"
    if code in "bdosxX":
        if code == "d":
            return "decimal-int"
        return "int" if code != "s" else "str"
    if code == "n":
        return "number"
    if code in "eEfFgG%":
        return "float-number"
    return None


def _merge_requirement(existing: str | None, new: str) -> str:
    if existing is None or existing == "any":
        return new
    if new == "any" or new == existing:
        return existing
    if {existing, new} <= {"stringable", "formattable"}:
        return "formattable"
    if existing in {"stringable", "formattable"}:
        return "decimal-int" if new == "int" else new
    if new in {"stringable", "formattable"}:
        return "decimal-int" if existing == "int" else existing
    if {existing, new} <= {"number", "float-number"}:
        return "float-number"
    if {existing, new} <= {"int", "decimal-int", "decimal", "number"}:
        if not {"int", "decimal-int"} & {existing, new}:
            return "decimal"
        return "decimal-int"
    if {existing, new} <= {"int", "char"}:
        return "codepoint"
    if "format-digits" in {existing, new} and {existing, new} <= {
        "format-digits", "codepoint", "char", "int", "decimal-int", "decimal", "number"
    }:
        return "format-digits"
    if "codepoint" in {existing, new} and {existing, new} <= {
        "codepoint", "char", "int", "decimal-int", "decimal", "number"
    }:
        return "codepoint"
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
            if match.group(0) != "%%":
                return PatternRequirements(
                    "unknown", "percent", reason="literal percent escape must be doubled without decorations"
                )
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
            if requirement is None:
                return PatternRequirements("unknown", "brace", reason="unmodeled brace format specification")
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
            # Nested fields occupy width/precision digit slots. Presence alone
            # does not establish that their substitution yields a valid spec.
            for _, nested, nested_spec, nested_conversion in Formatter().parse(spec):
                if nested is None:
                    continue
                if not re.fullmatch(r"[A-Za-z_]\w*", nested) or nested_spec or nested_conversion:
                    return PatternRequirements("unknown", "brace", reason="unsupported nested format field")
                brace_names.append(nested)
                brace_named_types[nested] = _merge_requirement(brace_named_types.get(nested), "format-digits")
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
    if requirement == "format-digits":
        return True if supplied == "bounded-nonnegative-int" else None
    if requirement in {"char", "codepoint"}:
        if supplied in {"bounded-nonnegative-int", "unicode-codepoint-int", "bool"}:
            return True
        if supplied in {"int", "finite-float-int", "float-overflow-int", "decimal-overflow-int"} or (requirement == "char" and supplied == "str"):
            return None
        return False
    if requirement == "float-number":
        if supplied == "int":
            return None  # An integer annotation alone does not bound conversion.
        return supplied in {"bounded-nonnegative-int", "unicode-codepoint-int", "finite-float-int",
                            "float", "finite-float", "nonfinite-float", "bool"}
    if requirement in {"stringable", "formattable", "decimal-int", "decimal", "number"}:
        if supplied == "decimal-overflow-int":
            return False
        if supplied == "int" and sys.get_int_max_str_digits():
            return None  # Decimal presentation needs a proven integer range.
    if supplied in {"bounded-nonnegative-int", "unicode-codepoint-int", "finite-float-int", "float-overflow-int", "decimal-overflow-int"}:
        supplied = "int"
    if requirement == "any":
        return True
    if requirement == "stringable":
        return True
    if requirement == "formattable":
        return supplied in {"int", "bool", "str", "float", "finite-float", "nonfinite-float", "number"}
    if requirement in {"int", "decimal-int"}:
        return supplied in {"int", "bool"}
    if requirement == "decimal":
        if supplied in {"float", "number"}:
            return None  # Finiteness is value-dependent for unresolved floats.
        return supplied in {"int", "bool", "finite-float"}
    if requirement == "number":
        return supplied in {"int", "float", "finite-float", "nonfinite-float", "number", "bool"}
    if requirement == "str":
        return supplied == "str"
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
    if not source_root.is_file() and not source_root.is_dir():
        raise ValueError(f"source path is not an existing file or directory: {source_root}")
    files = [source_root] if source_root.is_file() else sorted(source_root.rglob("*.py"))
    if len(files) > max_files:
        raise ValueError(f"source file budget exceeded: {len(files)} > {max_files}")
    calls: list[CallSite] = []
    flow_models: dict[tuple[str, int, int], list[_FlowModel]] = {}
    callees = dict(
        singular_callees=tuple(singular_callees), plural_callees=tuple(plural_callees),
        overloaded_callees=tuple(overloaded_callees),
        contextual_singular_callees=tuple(contextual_singular_callees),
        contextual_plural_callees=tuple(contextual_plural_callees),
    )
    for path in files:
        rel = path.name
        try:
            rel = str(path.resolve().relative_to(source_root)) if source_root.is_dir() else path.name
            source = path.read_text(encoding="utf-8")
            tree, nodes = _preflight(source, rel)
            file_calls = _scan_nodes(nodes, rel, **callees)
            if analysis_mode == "flow":
                recovered = _recover_flow_models(tree, **callees)
                for (line, column), models in recovered.items():
                    flow_models[(rel, line, column)] = models
            calls.extend(file_calls)
        except (SyntaxError, Unsupported, RecursionError, MemoryError) as exc:
            calls.append(_analysis_diagnostic(rel, exc))
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
                    try:
                        resolution = _flow_resolution(models, observation["count"])
                    except (Unsupported, RecursionError, MemoryError) as exc:
                        reason = f"flow qualification: {type(exc).__name__}: {exc}"
                        resolution = _FlowResolution(
                            Supplier("unknown", "none", reason=reason), (), reason, None,
                        )
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
    if not expected or not expected <= actual:
        raise AssertionError(("boundary recognition lost", expected - actual, report))
    if report["summary"]["literal_calls"] <= 0 or report["summary"]["selected_patterns"] <= 0:
        raise AssertionError(report)
    if report["summary"]["errors"] != 0 or report["summary"]["unknown"] != 0:
        raise AssertionError(report)
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
