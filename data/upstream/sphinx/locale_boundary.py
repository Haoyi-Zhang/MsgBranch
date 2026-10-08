"""Source-extracted registered-translator boundary, Sphinx 5c0d0438.
Copyright 2007-2016 by the Sphinx team. BSD-2-Clause.
The original get_translation function (including its uninitialized branch)
is retained below; registration helpers are original. _TranslationProxy and
_lazy_translate are deliberately not imported: this experiment registers
its translator before obtaining a translation function. No uninitialized
call is admitted. Non-executable docstrings of get_translation are omitted.
"""
from typing import Callable, Any

translators = {}


def get_translator(catalog: str = 'sphinx', namespace: str = 'general'):
    return translators[(namespace, catalog)]


def is_translator_registered(catalog: str = 'sphinx', namespace: str = 'general') -> bool:
    return (namespace, catalog) in translators


def get_translation(catalog: str, namespace: str = 'general') -> Callable:
    def gettext(message: str, *args: Any) -> str:
        if not is_translator_registered(catalog, namespace):
            # not initialized yet
            return _TranslationProxy(_lazy_translate, catalog, namespace, message)
        else:
            translator = get_translator(catalog, namespace)
            if len(args) <= 1:
                return translator.gettext(message)
            else:  # support pluralization
                return translator.ngettext(message, args[0], args[1])

    return gettext
