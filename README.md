# MsgBranch

MsgBranch qualifies localized-message failures at the boundary between catalog entries and the application code that supplies their arguments. It separates four layers that maintenance tools often conflate: catalog source, compiled runtime artifacts, application call sites, and locale-selected branches. Its project command performs bounded static recovery without importing target modules, executes the pinned Babel/gettext runtime on selected witnesses, and reports reviewable `clean`, `error`, or `unknown` findings.

## Reproduce

The reported measurements use Windows 11 on an Intel Core i7-12700KF, CPython 3.12.14, Babel 2.18.0, attrs 26.1.0, pytz 2026.2, Jinja2 3.1.6, and pytest 9.0.2. Python 3.12 and 3.13 are supported. Differential tests cover the version-sensitive gettext plural-expression helper.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/reproduce.py
python scripts/native_replay.py
python scripts/reproduce.py --full
```

All retained inputs run locally after dependency installation. No GPU, model API, paid service, credential, production system, or live third-party endpoint is used. The portable driver runs the current pytest suite as a checked stage before any study scripts, then verifies immutable inputs and licenses, executes four historical repair replays, evaluates the project analyzer and its direct-syntax ablation, checks retained two-project regressions, invokes the actual Babel CLI, and audits result accounting. A failed unit stage stops the driver. Native replay is a separate step that additionally executes all 384,384 retained generated inputs and their selected witnesses. Full mode regenerates both seeded studies and the cost measurements after the unit stage. Test counts are reported by pytest; the frozen study records do not establish a pass count for later source revisions.

Optional `jupyter_server==2.17.0` enables comparisons with the installed upstream method; otherwise the retained source slice runs and the optional comparison is recorded unavailable. Optional Node corroborates one `Intl.PluralRules` category result and is not treated as a second Fluent implementation.

## Boundary CLI

```sh
export PYTHONPATH="$PWD/src:$PWD/vendor/python-fluent"
python -m msgbranch.cli data/controls/reorder/call.py \
  data/controls/reorder/messages.po --planner partition
python -m msgbranch.cli data/controls/missing-at-100/call.py \
  data/controls/missing-at-100/messages.po --planner partition \
  --max-count 200 --output witness.json
```

Exit 0 means no violation was observed under the declared domain and implemented checks. Exit 1 means a qualified runtime failure or forbidden fallback was observed. Exit 2 means analysis is unavailable or unknown, which takes precedence. `--require-catalog` is appropriate only where source fallback violates the application obligation. The default planner is exhaustive; `--planner partition` explicitly selects the bounded predictive planner.

The boundary CLI interprets a restricted Python AST and never imports the supplied file. Domains are integer intervals within 0..10,000 with explicit cell and evaluation budgets. It supports gettext-family calls, percent formatting, brace formatting, contexts, branch-specific omissions, and primitive formatting type constraints. Unsupported fields, dynamic identifiers, unresolved values, and budget exhaustion remain unknown.

## Project auditor

```sh
msgbranch-project path/to/python/project path/to/messages.po \
  --max-count 200 --require-catalog \
  --output project-findings.json \
  --emit-pytest generated_regressions.py
```

`msgbranch-project` recursively parses Python without importing or executing the project. It recognizes literal `gettext`, `ngettext`, `pgettext`, and `npgettext` calls plus configurable wrappers. A bounded intraprocedural data-flow pass recovers local aliases, translation results formatted in later statements, dictionary and keyword suppliers, conditional suppliers over the count, and primitive supplier types. For each feasible count region, it crosses the recovered supplier shape with the branch selected by Babel-compiled `GNUTranslations`. Nested brace-format fields and percent conversion requirements are checked on the selected branch rather than against the union of every plural form.

Runtime branch sets are cached by catalog, domain, context, and message identity. Qualification remains call-site-specific, so two callers of the same message may receive different findings. Supported count-path conditions filter lookup/format uses, and a return terminates its local path. Unresolved reachability remains unknown; a call with no reachable boundary in the declared domain is not certified clean. Python `and`/`or` suppliers retain operand types and short-circuit alternatives. Evaluated children are inspected for local container mutations or escapes, including conditions and formatted strings; unsupported effects taint the affected supplier rather than discharge an obligation.

Generated pytest guards perform analyzer requalification, not native target execution. They preserve all five configured callee lists, the count bound, presence obligation and analysis mode. Each guard requires its recorded call/catalog boundary identities to remain recognized, a nonempty selected boundary set, and zero errors and unknowns. Review the paths and bindings before committing; regenerate after an intentional boundary move/removal. A project with no recognized boundaries cannot produce a guard.

Primitive percent tuples require exact positional arity; unused mapping keys remain permitted. Decimal percent conversions (`d`, `i`, `u`) admit finite literal floats as well as integers, while octal/hex percent and integer brace formats remain integer-only. Brace conversions (`!s`, `!r`, `!a`) produce strings before the format specification is checked. Value-dependent coercion, arbitrary objects, unmodeled format specifications and unsupported control flow are outside this bounded qualification model and can remain unknown. The owned regression fixtures compare these admitted cases with native Python formatting; they do not constitute an installed Jupyter-method comparison.

## Analyzer validation

The analyzer is validated in three complementary ways.

The figures below describe the retained study records. They are not a regeneration for every later analyzer revision; the current unit suite reports its own count and includes separate owned semantic and CI-guard regressions.

1. **Trusted controls.** Twenty-five constructed families cover legal reordering, branch-specific omission, contexts, nested fields, percent characters, type mismatch, count-dependent suppliers, and two intentionally unsupported cases. Across 4,623 direct reference executions, flow qualification matches all 25 control classifications with zero known false positives or false negatives. The direct-syntax ablation matches 7/25.
2. **Same-finding ablation.** On 25 controls plus six field slices, both analyzers inspect the same 47 call/catalog findings. Direct syntax yields 13 clean, 10 error, and 24 unknown findings. Bounded flow recovery yields 28 clean, 14 error, and 5 unknown findings: 15 unknown-to-clean and 4 unknown-to-error changes, with no clean/error regression to unknown.
3. **External regressions.** A Danish Solaar receiver boundary and an Estonian virt-manager installation-wait boundary contribute three clean call/catalog findings and ten agreeing native executions. These are known regression cases for the current analyzer, not a blind holdout or whole-project recall measurement.

## Evidence inventory

| Evidence | Recorded finding | Interpretation |
|---|---:|---|
| Sphinx repair | 24 observations | One lookup-kind repair; ordinary count-one and lookup-kind checks also detect it |
| OpenHangar repair | 248 boundary executions; 118 pre-repair failures, 0 after | One repair, not 118 defects; ordinary and identifier-conflict checks detect it |
| xrpldashboard repair | 4/4 pre-repair errors, 0/4 after | One interpolation-layer repair; ordinary count one detects it |
| AZM CRM repair | Missing MO resolves English source; compiled MO resolves Arabic | One artifact-delivery repair; artifact presence plus a runtime smoke test detects it |
| Public repair screen | 20 leads, 17 repair groups, four executable repairs | Frozen post-discovery ledger, not prevalence evidence |
| Trusted analyzer controls | 25/25 flow classifications exact; 7/25 direct | 4,623 direct executions; two unsupported cases remain unknown by construction |
| Project ablation | 47 findings: direct 13/10/24 vs flow 28/14/5 clean/error/unknown | Same findings and catalogs; 19 unknowns resolved without category regression |
| External regressions | 2 projects, 3 clean findings, 10 error-free executions | Independent adapted boundaries; no claim of exhaustive project coverage |
| Babel CLI | 227/227 MO/runtime outputs match; 225 accepted and 2 diagnosed format errors | Actual `pybabel compile`, plus format and encoding negative controls |
| Generated validation study | 52/52 active constructed mutations detected by product planning | 192 paired families; sensitivity analysis, not field-defect recall |
| Generated confirmation study | 54/54 active constructed mutations detected by product planning | Independently seeded paired study; same scope as above |
| Cost study | Product faster than exhaustive adapter in 12/12; direct native loop faster in 7/12 | Local boundary microbenchmarks only |
| Project scaling | 400 repeated calls use one lookup set; 400 unique calls use 400 | Cache effectiveness and local CPU cost, not service throughput |

The four executable historical repairs are all detected by a cheaper adequate check, so guard-product planning receives no field-yield credit. Its demonstrated contribution is narrower: it preserves supplier/locale interaction signatures in constructed cases when source-only or locale-only reduction loses them. The practitioner rule is therefore layered: compile and lint the catalog; verify the runtime artifact; qualify call sites; run ordinary native boundary values; add interaction planning only for a remaining declared obligation.

## Baselines and scope

Executed baselines include Babel catalog checks, the Babel CLI PO-to-MO path, Python `gettext`/`GNUTranslations`, direct native boundary execution, ordinary sample counts, key/placeholder checks, retained Weblate format-check components, retained LocalHero placeholder components, and the pinned Fluent runtime. The Weblate and LocalHero fixtures execute disclosed source components rather than complete applications. GNU `msgfmt`, a configured Weblate deployment, the complete LocalHero CLI, and full upstream application suites are not assigned miss counts because they were not executed.

MsgBranch checks technical compatibility and documented fallback obligations. It does not judge wording, grammar, cultural suitability, usability, or accessibility. It is intraprocedural and wrapper-configured: dynamic message construction, mutation through arbitrary containers, interprocedural dependency injection, reflection, and infeasible-path reasoning can remain unknown.

## Inspect the evidence

- `PROTOCOL.md` defines inclusion, separation of discovery/evaluation, oracles, and claim boundaries.
- `SOURCE-LEDGER.md` records immutable sources, transformations, and exclusions.
- `THIRD-PARTY-NOTICES.md` maps retained files to their licenses.
- `results/` contains raw runs, summaries, ablations, timing records, statistical receipts, and the independent result audit.
- `data/holdout/PROTOCOL.json` records source identities and the retained external-regression scope.
- `docs/references.csv` and `docs/references.json` are the verified bibliographic ledger used by the paper.

## Licensing and research assistance

New MsgBranch code and constructed fixtures are MIT. Retained third-party slices keep their original notices and licenses; the MsgBranch license does not relicense them. No fonts, credentials, chats, or private data are included.

Language models assisted with implementation, experiment scripting, literature organization, and prose drafting. Every reported numeric result is produced by the retained local programs, every cited source is present in the reference ledger, and no model-generated translation is evaluated as human linguistic evidence.
