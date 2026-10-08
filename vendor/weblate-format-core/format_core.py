# Copyright © Michal Čihař <michal@weblate.org>
# SPDX-License-Identifier: GPL-3.0-or-later
# Function-body excerpts from Weblate 5.13; see PROVENANCE.json.
# Packaging modifications: imports, ORM/UI superclass removal, and constructor
# wiring. The retained comparison/generator method bodies are upstream code.
from __future__ import annotations
import re
from collections import Counter, defaultdict
from itertools import chain
from gettext import c2py
from functools import lru_cache

PYTHON_PRINTF_MATCH = re.compile(
    r"""
    %(                          # initial %
          (?:\((?P<key>[^)]+)\))?    # Python style variables, like %(var)s
    (?P<fullvar>
        [ +#-]*                 # flags
        (?:\d+)?                # width
        (?:\.\d+)?              # precision
        (hh|h|l|ll)?         # length formatting
        (?P<type>[a-zA-Z%])        # type (%s, %d, etc.)
        |)                      # incomplete format string
    )""",
    re.VERBOSE,
)
PYTHON_BRACE_MATCH = re.compile(
    r"""
    }(})|                                 # escaped {
    {({)|                                 # escaped }
    {(                                  # initial {
        |                               # blank for position based
        (?P<field>
            [0-9]+|                     # numerical
            [_A-Za-z][_0-9A-Za-z]*      # identifier
        )
        (?P<attr>
            \.[_A-Za-z][_0-9A-Za-z]*    # attribute identifier
            |\[[^]]+\]                  # index identifier

        )*
        (?P<conversion>
            ![rsa]
        )?
        (?P<format_spec>
            :
            .?                          # fill
            [<>=^]?                     # align
            [+ -]?                      # sign
            [#]?                        # alternate
            0?                          # 0 prefix
            (?:[1-9][0-9]*)?            # width
            ,?                          # , separator
            (?:\.[1-9][0-9]*)?          # precision
            [bcdeEfFgGnosxX%]?          # type
        )?
    )}                          # trailing }
    """,
    re.VERBOSE,
)
def python_format_is_position_based(string: str):
    return "(" not in string and string not in {"{", "}"}
def name_format_is_position_based(string: str) -> bool:
    return not string
def extract_string_simple(match: re.Match) -> str:
    return match.group(1)
def extract_string_python_brace(match: re.Match) -> str:
    return match.group(1) or match.group(2) or match.group(3)

# Fixture replacement only: the upstream generator indexes a SimpleLazyObject
# around an already materialized example dictionary. No database access occurs.
def SimpleLazyObject(factory):
    return factory()

class BaseFormatCheck:
    regexp = None
    normalize_remove = set()
    def check_target_unit(self, sources, targets, unit):
        return any(self.check_generator(sources, targets, unit))
    def check_generator(self, sources, targets, unit):
        if len(sources) > 1 and len(targets) == 1:
            yield self.check_format(sources[1], targets[0], False, unit)
            return
        if (
            len(sources) > 1
            and not self.extract_matches(sources[0])
            and self.extract_matches(sources[1])
        ):
            source = sources[1]
        else:
            source = sources[0]
        plural_examples = SimpleLazyObject(lambda: unit.translation.plural.examples)
        yield self.check_format(
            source,
            targets[0],
            len(sources) > 1
            and "strict-format" not in unit.all_flags
            and (
                len(plural_examples[0]) == 1
                or (
                    plural_examples[0] == ["0", "1"]
                    and not unit.translation.component.file_format_cls.strict_format_plurals
                )
            ),
            unit,
        )
        if len(sources) == 1:
            return
        for i, target in enumerate(targets[1:]):
            yield self.check_format(
                sources[1], target, len(plural_examples[i + 1]) == 1, unit
            )
    def cleanup_string(self, text):
        return text
    def normalize(self, matches):
        if not self.normalize_remove:
            return matches
        return [m for m in matches if m not in self.normalize_remove]
    def extract_string(self, match):
        return extract_string_simple(match)
    def extract_matches(self, string):
        if self.regexp is None:
            return []
        return [
            self.cleanup_string(self.extract_string(match))
            for match in self.regexp.finditer(string)
        ]
    def check_format(self, source, target, ignore_missing, unit):
        if not target or not source:
            return False
        uses_position = True
        src_matches = self.normalize(self.extract_matches(source))
        if src_matches:
            uses_position = any(self.is_position_based(x) for x in src_matches)
        tgt_matches = self.normalize(self.extract_matches(target))
        missing = []
        extra = []
        if not uses_position:
            src_counter = Counter(src_matches)
            tgt_counter = Counter(tgt_matches)
            if src_counter != tgt_counter:
                missing = sorted(src_counter - tgt_counter)
                extra = sorted(tgt_counter - src_counter)
        elif src_matches != tgt_matches:
            for i in range(min(len(src_matches), len(tgt_matches))):
                if src_matches[i] != tgt_matches[i]:
                    missing.append(src_matches[i])
                    extra.append(tgt_matches[i])
            missing.extend(src_matches[len(tgt_matches) :])
            extra.extend(tgt_matches[len(src_matches) :])
        if ignore_missing and missing and not extra:
            return False
        if missing or extra:
            return {"missing": missing, "extra": extra}
        return False
    def is_position_based(self, string):
        return False

class PythonFormatCheck(BaseFormatCheck):
    # Original BasePrintfCheck flag wiring specialized to python-format.
    regexp = PYTHON_PRINTF_MATCH
    normalize_remove = {"%"}
    def is_position_based(self, string):
        return python_format_is_position_based(string)
    def cleanup_string(self, text):
        if "'" in text:
            return text.replace("'", "")
        return text

class PythonBraceFormatCheck(BaseFormatCheck):
    regexp = PYTHON_BRACE_MATCH
    normalize_remove = {"{", "}"}
    def extract_string(self, match):
        return extract_string_python_brace(match)
    def is_position_based(self, string):
        return name_format_is_position_based(string)
    def check_format(self, source, target, ignore_missing, unit):
        result = super().check_format(source, target, ignore_missing, unit)
        noformat = PYTHON_BRACE_MATCH.sub("", target)
        add_extra = [char for char in ("{", "}") if char in noformat]
        if add_extra:
            if isinstance(result, dict):
                result["extra"].extend(add_extra)
            else:
                result = {"missing": [], "extra": add_extra}
        return result

@lru_cache(maxsize=128)
def plural_examples(formula):
    # Original Plural.examples method body; self.plural_function is replaced
    # with the same native c2py(formula) that its upstream property constructs.
    result = defaultdict(list)
    func = c2py(formula or '0')
    for i in chain(range(10000), range(10000, 2000001, 1000)):
        ret = func(i)
        if len(result[ret]) >= 10:
            continue
        result[ret].append(str(i))
    for example in result.values():
        if len(example) >= 10:
            example.append("…")
    return result
