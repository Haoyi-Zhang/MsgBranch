# Retained project-scan measurements

These two files are byte-preserved copies of the supplied artifact's
`results/project-scaling.json` and `results/project-scaling-stdout.json`, retained
before replacing the default scaling result with a new source-bound measurement.
The primary JSON contains the previously reported three-repeat measurements;
the compact stdout file contains different values and is preserved as a distinct
historical record, not asserted to be the stdout of that primary JSON.

The records do not identify their actual execution UTC or scanner-source hash.
Those missing historical facts remain unknown. Preservation hashes identify the
retained bytes, not the executable or environment of the historical runs:

- `project-scaling.json`: SHA-256 `0f3a8b5c82b2cdf4bc1ba76946b9201b8da13cc4524034ad79ac8c0f41e0d12f`.
- `project-scaling-stdout.json`: SHA-256 `0b130fb2ec37095fc50a47be61345a7c4d996095c5b92eb06a6d85a44233c83f`.

Current paper consumers read `results/project-scaling.json`, not this archive.
New measurements retain their own actual UTC, environment, source bindings and
generated fixture bytes separately. Neither old nor new scan observations enter
the 26-control denominator or the frozen generated-study denominators.
