"""Stronger, cheap call/catalog baseline; unknown wrappers are never guessed."""
import ast
from .runtime import CatalogRuntime

def lookup_kind_conflicts(source: str, rt: CatalogRuntime, *, plural_callees=('ngettext',), overloaded_callees=()):
    """Diagnose an ngettext call whose available catalog entry is non-plural.

    This is a potential obligation violation, not a universal missing-translation
    error. The caller must establish the wrapper binding and intended use of the
    translation. Empty targets are recorded but not alarming.
    """
    records=[]
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name):
            continue
        callee=node.func.id
        is_plural=callee in plural_callees or (callee in overloaded_callees and len(node.args)==3)
        if not is_plural or len(node.args)!=3:
            continue
        if not all(isinstance(x,ast.Constant) and isinstance(x.value,str) for x in node.args[:2]):
            records.append({'line':node.lineno,'status':'unknown-dynamic-key','alarm':False})
            continue
        message=rt.catalog.get(node.args[0].value)
        if message is not None and not message.pluralizable:
            records.append({'line':node.lineno,'key':node.args[0].value,'status':'nonplural-entry-at-plural-call',
                            'translated_value_present':bool(message.string),'alarm':bool(message.string) and not message.fuzzy})
    return records
