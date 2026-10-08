# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bedrock method excerpts; explicit dependency substitutions documented nearby.
No Django settings, caches, decorators, middleware or server are executed.
"""
from functools import cached_property
from pathlib import Path
from fluent.runtime.fallback import FluentLocalization
from fluent.syntax import FluentParser

def FluentResource(source):
    return FluentParser().parse(source)

class FluentL10n(FluentLocalization):
    def _localized_bundles(self):
        for bundle in self._bundles():
            if bundle.locales[0] == self.locales[0]:
                yield bundle

    @cached_property
    def _localized_message_ids(self):
        messages = set()
        for bundle in self._localized_bundles():
            messages.update(bundle._messages.keys())
        return list(messages)

    def has_message(self, message_id):
        # assume English locales have the message
        if self.locales[0].startswith("en-"):
            return True
        return message_id in self._localized_message_ids


def translate(l10n, message_id, fallback=None, **kwargs):
    # check the `locale` bundle for the message if we have a fallback defined
    if fallback and l10n.has_message(fallback) and not l10n.has_message(message_id):
        message_id = fallback
    return l10n.format_value(message_id, kwargs)

class FixtureLoader:
    """Harness: supply one fixture root and preserve Bedrock brand injection order."""
    def resources(self, locale, resource_ids):
        root = Path(__file__).parent
        resources = []
        for resource_id in resource_ids:
            path = root / locale / resource_id
            if path.is_file():
                resources.append(FluentResource(path.read_text(encoding="utf-8")))
        if resources:
            if locale != "en":
                resources.append(FluentResource((root / "en/brands.ftl").read_text(encoding="utf-8")))
            yield resources

def get_l10n(locales=None):
    return FluentL10n(locales or ["de", "en"], ["mozorg/fluent.ftl", "brands.ftl"], FixtureLoader())
