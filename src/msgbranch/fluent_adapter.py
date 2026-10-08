"""Observation adapter for the pinned python-fluent source, not a second evaluator.

Single-threaded local tests only. Captures actual runtime choices with a temporary
Python profile hook; restores the caller's hook. Existing profilers are rejected.
Use trusted bounded resources and call suppliers. No whole-project completeness.
"""
from __future__ import annotations

import ast
from contextlib import AbstractContextManager
from decimal import Decimal
from itertools import product
from typing import Any
import sys

from fluent.syntax import FluentParser
from fluent.syntax import ast as FTL
from fluent.runtime import resolver
from fluent.runtime.bundle import FluentBundle
from fluent.runtime.types import FluentNone


def scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, FluentNone):
        return {"fluent_none": value.name}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"type": type(value).__name__}


class Trace(AbstractContextManager):
    def __init__(self):
        self.branches: list[dict] = []
        self.reads: list[dict] = []
        self.formats: list[dict] = []
        self.lookups: list[dict] = []
        self._matched: dict[int, bool] = {}
        self._previous = None
        self._active = False

    def _profile(self, frame, event, value):
        code = frame.f_code
        if code is resolver.SelectExpression.__call__.__code__:
            if event == "call":
                self._matched[id(frame)] = False
            elif event == "return":
                found = frame.f_locals.get("found")
                node = frame.f_locals["self"]
                key = getattr(found, "key", None)
                self.branches.append({
                    "span": node.span.start if node.span else None,
                    "selector": scalar(frame.f_locals.get("key")),
                    "variant": scalar(getattr(key, "name", getattr(key, "value", None))),
                    "declared_default": bool(getattr(found, "default", False)),
                    "selection": "match" if self._matched.pop(id(frame), False) else "default-fallthrough",
                })
        elif code is resolver.match.__code__ and event == "return" and value:
            parent = frame.f_back
            if parent is not None and parent.f_code is resolver.SelectExpression.__call__.__code__:
                self._matched[id(parent)] = True
        elif code is resolver.VariableReference.__call__.__code__ and event == "return":
            env, node = frame.f_locals["env"], frame.f_locals["self"]
            name = node.id.name
            self.reads.append({"name": name, "present": name in env.current.args,
                               "scope": "external" if env.current.error_for_missing_arg else "term-parameter",
                               "type": type(env.current.args[name]).__name__ if name in env.current.args else "missing"})
        elif code is FluentBundle.format_pattern.__code__ and event == "return" and isinstance(value, tuple):
            self.formats.append({"locales": frame.f_locals["self"].locales,
                                 "output": str(value[0]),
                                 "errors": [{"type": type(e).__name__, "message": str(e)} for e in value[1]]})
        elif code is FluentBundle.has_message.__code__ and event == "return":
            self.lookups.append({"locales": frame.f_locals["self"].locales,
                                 "id": frame.f_locals["message_id"], "present": bool(value)})

    def __enter__(self):
        self._previous = sys.getprofile()
        if self._previous is not None or self._active:
            raise RuntimeError("Trace requires a single-threaded test without another profiler")
        self._active = True
        sys.setprofile(self._profile)
        return self

    def __exit__(self, exc_type, exc, tb):
        sys.setprofile(self._previous)
        self._active = False
        return False

    def result(self) -> dict:
        return {"branches": self.branches, "reads": self.reads,
                "formats": self.formats, "lookups": self.lookups,
                "needed_external": sorted({x["name"] for x in self.reads if x["scope"] == "external"})}


def parse_bounded(source: str):
    if len(source.encode()) > 100_000:
        raise ValueError("resource exceeds 100 KB boundary")
    resource = FluentParser().parse(source)
    junk = [n for n in resource.body if isinstance(n, FTL.Junk)]
    if junk:
        raise ValueError("FTL parse errors: " + "; ".join(a.message or a.code for n in junk for a in n.annotations))
    return resource


def candidate_values(source: str, message_id: str, max_count: int = 200) -> dict:
    """Finite input suggestions, NOT branch reachability or whole-resource proof.

    Traverses message/term references for candidate keys. Runtime traces, not these
    keys, establish selection. Custom function selectors are explicitly unknown.
    Numeric and string call contracts must choose which candidates are admissible.
    """
    if not 0 <= max_count <= 1000:
        raise ValueError("max_count must be in 0..1000")
    resource = parse_bounded(source)
    entries = {(('-' if isinstance(n, FTL.Term) else '') + n.id.name): n
               for n in resource.body if isinstance(n, (FTL.Message, FTL.Term))}
    if message_id not in entries:
        return {"values": [], "unknown": ["missing message ID"], "variant_nodes": 0}
    values: list[Any] = list(range(max_count + 1))
    unknown, seen = [], set()
    variants = 0
    budget = 4000
    def walk(node, depth=0):
        nonlocal budget, variants
        budget -= 1
        if budget < 0 or depth > 40:
            raise ValueError("resource traversal limit")
        if isinstance(node, FTL.SelectExpression):
            variants += len(node.variants)
            s = node.selector
            if isinstance(s, FTL.FunctionReference) and s.id.name != "NUMBER":
                unknown.append("custom/function selector: " + s.id.name)
            elif not isinstance(s, (FTL.VariableReference, FTL.FunctionReference, FTL.NumberLiteral, FTL.StringLiteral)):
                unknown.append("unsupported selector: " + type(s).__name__)
            for v in node.variants:
                if isinstance(v.key, FTL.NumberLiteral):
                    values.append(float(v.key.value) if '.' in v.key.value else int(v.key.value))
                else:
                    values.append(v.key.name)
        if isinstance(node, (FTL.MessageReference, FTL.TermReference)):
            name = ('-' if isinstance(node, FTL.TermReference) else '') + node.id.name
            if name not in entries:
                unknown.append("unresolved reference: " + name)
            elif name not in seen:
                seen.add(name); walk(entries[name], depth + 1)
        if isinstance(node, FTL.BaseNode):
            for name, val in vars(node).items():
                if name == 'span': continue
                if isinstance(val, FTL.BaseNode): walk(val, depth + 1)
                elif isinstance(val, list):
                    for child in val:
                        if isinstance(child, FTL.BaseNode): walk(child, depth + 1)
    seen.add(message_id); walk(entries[message_id])
    unique = {}
    for value in values:
        unique[(type(value).__name__, repr(value))] = value
    return {"values": list(unique.values()), "unknown": sorted(set(unknown)), "variant_nodes": variants}


def literal_calls(source: str) -> list[dict]:
    """Recover literal format_value IDs/dict arguments; everything else is unknown.

    Binding to FluentLocalization is a caller-verified integration precondition.
    This helper does not infer imports, execute source, or assume dynamic args exist.
    """
    if len(source) > 100_000: raise ValueError("source limit")
    tree = ast.parse(source)
    if sum(1 for _ in ast.walk(tree)) > 3000: raise ValueError("AST limit")
    rows = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format_value'):
            continue
        row = {"line": node.lineno, "status": "unknown"}
        if node.keywords or not 1 <= len(node.args) <= 2:
            row['reason'] = 'unsupported call signature'
        else:
            try:
                key = ast.literal_eval(node.args[0])
                args = ast.literal_eval(node.args[1]) if len(node.args) == 2 else {}
                if not isinstance(key, str) or not isinstance(args, dict) or not all(isinstance(k,str) for k in args):
                    raise ValueError()
                if not all(v is None or type(v) in (str,int,float,bool) for v in args.values()):
                    raise ValueError()
                row.update(status='literal', message=key, args=args)
            except (ValueError, TypeError):
                row['reason'] = 'dynamic ID or argument supplier'
        rows.append(row)
    return rows


def signature(trace: dict, args: dict, include_shape: bool = True) -> tuple:
    branches = tuple((x['span'], repr(x['variant']), x['selection']) for x in trace['branches'])
    reads = tuple((x['name'],x['scope'],x['present'],x['type']) for x in trace['reads']) if include_shape else ()
    shape = tuple(sorted((k,type(v).__name__) for k,v in args.items())) if include_shape else ()
    return branches, reads, shape
