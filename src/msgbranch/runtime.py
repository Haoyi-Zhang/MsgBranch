"""Real gettext execution and catalog-local observations (no fallback inference from prose)."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
import gettext
import re
from typing import Any
from babel.messages.pofile import read_po
from babel.messages.mofile import write_mo

@dataclass
class Lookup:
    method: str
    singular: str
    plural: str | None
    count: int | None
    branch: int | None
    resolution: str
    output: str
    context: str | None = None

class CatalogRuntime:
    """PO -> Babel's real MO writer -> Python's real GNUTranslations.

    Only catalog-local lookup and Python's default source fallback are admitted.
    Trace metadata reads the runtime's catalog; selection/output are delegated.
    Multi-domain fallback chains are explicitly outside this adapter.
    """
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.stat().st_size > 8_000_000:
            raise ValueError('catalog exceeds the bounded 8 MB input budget')
        with self.path.open('rb') as fp:
            self.catalog = read_po(fp, abort_invalid=True)
        self.checks = [{'message': str(m.id), 'errors': [str(e) for e in errors]}
                       for m, errors in self.catalog.check()]
        fp = BytesIO()
        write_mo(fp, self.catalog, use_fuzzy=False)
        self.mo = fp.getvalue()
        self.translator = gettext.GNUTranslations(BytesIO(self.mo))
        self.trace: list[Lookup] = []

    def _plural_origin(self, message: str, index: int, context: str | None = None) -> str:
        entry = self.catalog.get(message, context=context)
        if entry is not None and isinstance(entry.string, (tuple, list)) and index < len(entry.string) and not entry.string[index]:
            return 'compiler-source-substitution'
        return 'catalog'

    def reset(self) -> None:
        self.trace.clear()

    def gettext(self, message: str) -> str:
        result = self.translator.gettext(message)
        # GNUTranslations.gettext can select the plural entry for n=1.
        index = self.translator.plural(1)
        if message in self.translator._catalog:
            resolution = 'catalog'
        elif (message, index) in self.translator._catalog:
            origin = self._plural_origin(message, index)
            resolution = 'catalog-plural-at-one' if origin == 'catalog' else origin
        else:
            resolution = 'source-fallback'
        self.trace.append(Lookup('gettext', message, None, None, None, resolution, result))
        return result

    def ngettext(self, singular: str, plural: str, count: int) -> str:
        if type(count) is not int:
            raise TypeError('MsgBranch gettext adapter admits only integer counts')
        index = self.translator.plural(count)
        result = self.translator.ngettext(singular, plural, count)
        resolution = self._plural_origin(singular, index) if (singular, index) in self.translator._catalog else 'source-fallback'
        self.trace.append(Lookup('ngettext', singular, plural, count, index, resolution, result))
        return result


    def pgettext(self, context: str, message: str) -> str:
        result = self.translator.pgettext(context, message)
        key = f"{context}\x04{message}"
        index = self.translator.plural(1)
        if key in self.translator._catalog:
            resolution = 'catalog'
        elif (key, index) in self.translator._catalog:
            resolution = 'catalog-plural-at-one'
        else:
            resolution = 'source-fallback'
        self.trace.append(Lookup('pgettext', message, None, None, None, resolution, result, context))
        return result

    def npgettext(self, context: str, singular: str, plural: str, count: int) -> str:
        if type(count) is not int:
            raise TypeError('MsgBranch gettext adapter admits only integer counts')
        index = self.translator.plural(count)
        result = self.translator.npgettext(context, singular, plural, count)
        key = f"{context}\x04{singular}"
        resolution = self._plural_origin(singular, index, context=context) if (key, index) in self.translator._catalog else 'source-fallback'
        self.trace.append(Lookup('npgettext', singular, plural, count, index, resolution, result, context))
        return result

    def sphinx(self, message: str, *args: Any) -> str:
        """The registered Sphinx get_translation dispatch, not a generic wrapper."""
        if len(args) <= 1:
            return self.gettext(message)
        return self.ngettext(message, args[0], args[1])

    def serialize_trace(self) -> list[dict[str, Any]]:
        return [asdict(x) for x in self.trace]

_PERCENT = re.compile(r'%(?:\(([^)]+)\))?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?([diouxXeEfFgGcrsa%])')
def named_percent_fields(text: str) -> set[str]:
    return {m.group(1) for m in _PERCENT.finditer(text) if m.group(1) is not None}

def placeholder_set_alarm(catalog) -> bool:
    """Deliberately naive paired-form named-placeholder equality baseline.
    Extra locale forms are compared with the source plural. Empty translations
    are not errors in this baseline; positional formatting is not supported.
    """
    for m in catalog:
        if not m.id:
            continue
        source = m.id if isinstance(m.id, (list, tuple)) else (m.id,)
        target = m.string if isinstance(m.string, (list, tuple)) else (m.string,)
        for i, translated in enumerate(target):
            if translated and named_percent_fields(source[min(i, len(source)-1)]) != named_percent_fields(translated):
                return True
    return False
