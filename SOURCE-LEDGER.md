> Earlier discovery entries are preserved below as historical notes. Current execution scope is in README.md, results/availability.json, and the revision additions at the end. An earlier unavailable component is not a statement about the later source-excerpt run.

# Source and case ledger

Acquired/reviewed 2026-09-30. This ledger is an evidence-role record, not an exhaustive search, an independent annotation exercise, or a claim of upstream adoption. Discovery and tuning cases were not held out. No maintainer was contacted.

## Reconstructed historical repair: Sphinx

- Report: https://github.com/sphinx-doc/sphinx/issues/7282 — “Strings should be in plural forms, but are not treated as such,” opened March 9, 2020; closed March 14, 2020.
- Repair: https://github.com/sphinx-doc/sphinx/commit/6682f89871b8df9bb4d85cab5b8f35c9396c9afb — “Fix #7282: i18n: messages using ngettext() does not translated.” Author/committer: Takeshi KOMIYA, March 14, 2020.
- Parent: `5c0d0438c4b1f4e2277fd5d79fcd06e80bb65f20`.
- Source paths: `sphinx/application.py`, `sphinx/locale/__init__.py`, `sphinx/locale/ja/LC_MESSAGES/sphinx.po`, `sphinx/locale/de/LC_MESSAGES/sphinx.po`, `setup.cfg`, `LICENSE`.
- Acquisition: public GitHub source/commit reads. Local application slices remove logger/color operations, return the formatted string, and introduce a function boundary. The locale wrapper retains the registered path. The two PO files retain only relevant entries and their header/attribution, not entire catalogs. Exact transformations and retained-file SHA-256 values are in `data/upstream/sphinx/PROVENANCE.json`.
- Oracle: old Japanese count-one call bypasses the existing translated singular entry; the historical change restores it. German empty translation is a permitted fallback control, not a second defect. Other counts/locales are executions of the same repair, not independent bugs.
- Competing explanation: ordinary count-one execution with the same assertion, lookup-kind checking, and appropriate extraction configuration suffice. No additional real detection benefit established.
- Contemporary local reconstruction uses Python 3.13.5 and Babel 2.18.0, not the historical application's complete environment or suite.

Example retrieval commands for independent inspection (not needed to run the retained fixtures):

```sh
BASE=https://raw.githubusercontent.com/sphinx-doc/sphinx
BEFORE=5c0d0438c4b1f4e2277fd5d79fcd06e80bb65f20
AFTER=6682f89871b8df9bb4d85cab5b8f35c9396c9afb
curl -fL "$BASE/$BEFORE/sphinx/application.py" -o application-before.py
curl -fL "$BASE/$AFTER/sphinx/application.py" -o application-after.py
curl -fL "$BASE/$BEFORE/sphinx/locale/__init__.py" -o locale-original.py
curl -fL "$BASE/$BEFORE/setup.cfg" -o setup-original.cfg
```

## Neutral local application boundary: Jupyter Server

Version 2.17.0, acquired from the installed distribution. Upstream https://github.com/jupyter-server/jupyter_server/tree/v2.17.0 . The exact dedented `ServerApp.running_server_info` method, complete installed Chinese PO, `transutils.py`, BSD license and source SHA-256 hashes are retained. The translation catalog is deliberately injected. The retained source-slice record covers 201 count states using authored local objects. The current primary `results/jupyter-summary.json` marks installed-method comparison unavailable because the optional native package is not installed; no four-count installed-Jupyter differential is credited. The separate historical `results/jupyter-stdout.json` retains four match entries at counts 0, 1, 2, and 100 unchanged. Those entries do not resolve the primary summary's unavailable status, and their lineage has not been newly established. The supported scope is source-slice behavior and native Python interpolation, not locale discovery, network startup, kernels, or production configuration. Source inspection preceded admission; not held out. No defect is attributed to Jupyter.

## Real Fluent runtime, constructed messages and contract probes

https://github.com/projectfluent/python-fluent/tree/e95b07ea07966dec064d09398a265222742bcfa2 . Exact source-file URLs and blob hashes are in `vendor/python-fluent/PROVENANCE.json`; verify with `python scripts/verify_vendor.py`. Twelve upstream executable files are unchanged. The package initializer shim and omitted optional modules are documented there. Apache-2.0 notices and license are included.

The official usage examples and selector/term/error documentation were reviewed. Four high-level API calls reproduce documented fallback or deliberately constructed error recovery. Four mutation families are artificial. Decimal exact-match and formatting-sensitive category probes are exploratory runtime-contract observations after source inspection. They have neither an independently replayed downstream application nor maintainer confirmation. An optional Node Intl category check corroborates one expectation after discovery; it is not a second Fluent implementation. No issue-search result is treated as proof of novelty.

## Excluded or unavailable discovery leads

| Lead | Role and disposition |
|---|---|
| https://github.com/WeblateOrg/weblate/issues/13016 | Public placeholder/plural behavior report; not presumed confirmed bug. No matching deployed Weblate instance was evaluated. |
| https://github.com/orgs/organicmaps/discussions/4515 | “Weblate for localizing app UI string resources”; maintenance context only. Its application integration was not included in the Python adapters. |
| Kiwi commit `c4c37fec65dc31ccfbb0381214d1e1a32984fd8a` | https://github.com/kiwitcms/Kiwi/commit/c4c37fec65dc31ccfbb0381214d1e1a32984fd8a ; inspected repair changes test formatting; excluded from application-defect counts. |
| Miro commit `93d34232bd9c404be80e6af2b5ce84e0cb94c0c8` | https://github.com/pculture/miro/commit/93d34232bd9c404be80e6af2b5ce84e0cb94c0c8 ; catalog/KeyError handling lead; no complete matching-version catalog/call replay obtained. Excluded. |
| SecureDrop commit `45e9b387cebdedcbc83a118af397b6bb7de45df2` | Plural-migration search lead; no independent defect oracle/replay. Not a validated case or retained source input. |


## Tool execution and comparison gaps

Executed locally: Babel catalog checkers; the actual Babel 2.18.0 `pybabel compile --use-fuzzy` command; Python `gettext`/`GNUTranslations`; the pinned Fluent parser/runtime; source-preserving application slices; the non-executing project auditor; the Weblate 5.13 Python-format/brace-format components; the LocalHero `af81321a` placeholder component; synthetic reference execution; and the test suite. The Babel CLI run covers all 27 frozen catalogs plus two negative controls and is separately receipted in `results/babel-cli.json`.

Not executed: GNU msgfmt, a configured full Weblate deployment, the complete LocalHero CLI, or complete upstream Sphinx/Jupyter/OpenHangar/xrpldashboard/AZM/Bedrock suites. Unavailable or unexecuted baselines are not assigned a miss count. The GNU command retained for an equivalent future check is `msgfmt --check --check-format -o /dev/null messages.po`, with applicable PO format flags. No AI translation service, quality add-on or external model participates in the measurements.

## Retained source additions

| Material | Immutable source / local receipt | Role and limit |
|---|---|---|
| OpenHangar | Parent `3267c9f875db7ad5b3f16b7bcc91c3cf32de1634`; repair `930cefba3aa19ace7b440d2efdbd0f341bf35d5c`; `data/openhangar/PROVENANCE.json` | One historical call/catalog repair; exact Jinja expressions and catalog excerpts, not application execution |
| Bedrock | `81541a0fccb1211ce284d1ed11866e54094bc5df`; `data/bedrock/PROVENANCE.json` | Five exact FTL files and seven normal expected outputs; adapted boundary/loader, not full suite |
| Weblate component | Tag `weblate-5.13`, format blob `898f729ca97c4e50fc62104eacdac646476aab88`, plural-model blob `84153dd4cdb2d35937a833b4b6710c2450c0eec0` | Executed format source excerpts; no full Weblate or ORM integration |
| CPython parser | `v3.13.5`, `Lib/gettext.py`, blob `62cff81b7b3d496f798222ec1ca64cbb9c9a2273` | Version-sensitive plural-expression parsing; only CPython 3.13.5 validated |
| Babel | `v2.18.0`; checker blob `4026ab1b3274deead5cf3fce2a31ea647991cf54`; installed CLI receipt | Catalog checks and real PO→MO command path; not GNU msgfmt |
| Generated studies | `data/validation/protocol.json`, `data/confirmation/protocol.json` | Fully retained constructed paired sensitivities; not sampled field defects |
| xrpldashboard | Repair `e03829d58f6c1acdf16b69e3aa168b93f3782586`; `data/xrpldashboard/PROVENANCE.json` | Exact changed Jinja expression and MIT notice; behavioral slice, not full route/application |
| LocalHero | Commit `af81321af193458f5869befec4481b8507c2d78d`; `vendor/localhero/PROVENANCE.json` | Compiled/executed placeholder core; no discovery/configuration/service path |
| AZM CRM build boundary | Parent `730e121364558e1e4c971e9f86bd4d620d783fca`; repair `326d0f9d0d964eef90ebc33f5303c26a0f24064f`; `data/azm-build/PROVENANCE.json` | Missing-MO delivery replay with one short message pair; no Django application/suite; no repository license located |
| Project audit | `src/msgbranch/project.py`, `results/project-audit.json`, `results/project-scaling.json` | Non-executing literal-call qualification; dynamic/indirect suppliers remain unknown |
| Public-fix screen | `corpus/public-fix-screen.json`, CSV and protocol | 20 leads, 17 groups, four executable repairs; post-discovery ledger, not systematic mining or prevalence |
| Statistical receipt | `results/statistical-analysis.json` and CSV | Wilson intervals and exact paired McNemar tests over constructed families only |


The bibliographic ledger contains 69 cited sources. Earlier discovery notes remain evidence-role history, not a statement that every candidate was executed or admitted. Known inaccessible full texts, unconfirmed runtime-contract probes, absent maintainer confirmation and absent industrial rollout remain explicit.

## Post-freeze independent-project holdout

| Project | Immutable source | Retained boundary | Role and limitation |
|---|---|---|---|
| Solaar | `pwr-Solaar/Solaar` commit `e7304c4c451cc9bb4f206a914844525e67856a28`; `data/holdout/solaar/PROVENANCE.json` | Receiver zero guard plus the exact Danish `gettext`/`ngettext` messages and named count supplier | Analyzer selected only after the analyzer-module hashes were frozen; adapted function boundary, not a whole-project audit or defect |
| virt-manager | `virt-manager/virt-manager` commit `bac5379d085219457a39c5e7c2a5855919d58ef8`; `data/holdout/virt-manager/PROVENANCE.json` | Installation-wait `ngettext` call plus the exact Estonian plural entries and integer supplier | Same post-freeze rule; adapted method boundary, not a whole-project audit or linguistic judgment |

The holdout protocol and frozen analyzer hashes are in `data/holdout/PROTOCOL.json`. Both retained source slices are GPL-2.0-compatible materials distributed with the corresponding license text. Their three call/catalog findings and ten native executions are portability checks and are not added to the historical-defect denominator.
