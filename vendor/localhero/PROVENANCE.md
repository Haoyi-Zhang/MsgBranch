# LocalHero placeholder-check component provenance

- Upstream repository: `localheroai/cli`
- Commit: `af81321af193458f5869befec4481b8507c2d78d`
- Commit title: `Add offline check command (#85)`
- Upstream paths: `src/utils/check-utils.ts`, `src/utils/placeholders.ts`, `LICENSE`
- Retrieval date: 2026-10-03
- License: MIT; retained in `LICENSE`

`placeholders.ts` retains the dependency-free placeholder parser used by the
upstream command. `check-utils.ts` retains only `toStringValue`,
`findPlaceholderMismatches`, and their direct plural-key helpers; unrelated
orphan, shape, empty/identical, duplicate-key, and missing-category checks are
omitted. Comments at the file heads identify the excerpt. The experiment is
therefore an executed source-component comparison, not execution of the full
LocalHero CLI, file discovery, configuration, or reporting stack.

The local runner receives already flattened source/target maps. It treats an
upstream `hint` as a hint rather than an error. The component has no visibility
into application callers, so clean/mutant functions sharing a catalog are
expected to receive identical catalog results.
