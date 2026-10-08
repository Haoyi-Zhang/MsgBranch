"""Fixture harness for the separately licensed Weblate format-core excerpts.

This is not the Weblate application. It has no ORM, queue, UI, component discovery
or Fluent checks. Only enabled Python percent/brace checks are run. A source unit
without either format flag is reported as not applicable, not as checked.
"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util

PATH=Path(__file__).resolve().parents[2]/'vendor/weblate-format-core/format_core.py'
spec=importlib.util.spec_from_file_location('msgbranch_vendor_weblate_core',PATH)
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

def check_catalog(catalog, *, strict=False):
    flags={'strict-format'} if strict else set()
    unit=SimpleNamespace(all_flags=flags, translation=SimpleNamespace(
        plural=SimpleNamespace(examples=core.plural_examples(catalog.plural_expr)),
        component=SimpleNamespace(file_format_cls=SimpleNamespace(strict_format_plurals=False))))
    rows=[]
    for m in catalog:
        if not m.id: continue
        sources=list(m.id) if isinstance(m.id,tuple) else [m.id]
        targets=list(m.string) if isinstance(m.string,(tuple,list)) else [m.string or '']
        for flag,cls in [('python-format',core.PythonFormatCheck),('python-brace-format',core.PythonBraceFormatCheck)]:
            if flag not in m.flags: continue
            unit.all_flags=flags|set(m.flags)
            result=list(cls().check_generator(sources,targets,unit))
            rows.append({'message_id':m.id,'format_flag':flag,'strict':strict,
                         'fuzzy':m.fuzzy,'alarm':any(bool(x) for x in result),'details':result})
    return rows
