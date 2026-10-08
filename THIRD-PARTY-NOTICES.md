# Third-party material

New MsgBranch code and constructed fixtures are MIT. That grant does not replace upstream conditions. Retained third-party material remains separately licensed or, where no license was located, narrowly quoted and explicitly limited:

| Material | License / location |
|---|---|
| Sphinx boundary/catalog excerpts | BSD, `data/upstream/sphinx/` notices |
| Jupyter Server method/catalog | BSD, `data/upstream/jupyter/` notices |
| python-fluent source subset | Apache-2.0, `vendor/python-fluent/` license and provenance |
| OpenHangar catalog/call excerpts | MIT, `data/openhangar/LICENSE` |
| Bedrock FTL/boundary excerpts | MPL-2.0, `data/bedrock/MPL-2.0.txt` and file notices |
| Weblate Python format component excerpts | GPL-3.0-or-later, `vendor/weblate-format-core/COPYING` and source notice |
| LocalHero placeholder/check component | MIT, `vendor/localhero/LICENSE` and provenance |
| xrpldashboard changed Jinja expression | MIT, `data/xrpldashboard/LICENSE` and provenance |
| AZM CRM build-boundary message pair | No repository license located at the frozen revision; one short identifier/translation pair retained as research evidence, `data/azm-build/PROVENANCE.json` |
| Solaar holdout boundary/catalog | GPL-2.0-or-later source slice; repository GPL-2.0 metadata, `data/holdout/solaar/GPL-2.0.txt` and provenance |
| virt-manager holdout boundary/catalog | GPL-2.0, `data/holdout/virt-manager/GPL-2.0.txt` and provenance |

Adapted files are documented in each `PROVENANCE.json`; exact upstream blob identity is asserted only for complete verified files. Weblate and LocalHero use minimal fixture harnesses and are not distributed as their full applications. Consult their licenses before reuse; the MsgBranch MIT notice does not relicense them. Babel, attrs, Jinja2 and pytz are installed dependencies rather than vendored source. No font files are included.
