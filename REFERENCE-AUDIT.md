# Reference audit

The manuscript cites 69 distinct bibliographic sources: scholarly papers, one author-posted replication dataset, standards, documentation, source code, issues, and immutable repair or holdout records. The sources are not represented as 69 research papers or as 69 fully accessible texts. Verification locations, access levels, and manuscript roles are in `docs/references.json` and `docs/references.csv`.

The 2026 systematic mapping study and TString were checked at the access level recorded in the ledger; no unavailable full-text quantitative result is used. `scripts/reference_audit.py` verifies BibTeX/citation/JSON/CSV key agreement, duplicate keys, duplicate DOI values, and duplicate canonical URLs.

Recorded receipt: 70 BibTeX entries including the IEEE control record, 69 bibliographic sources, 69 unique cited keys, 69 JSON records, and 69 CSV records. All audit error lists are empty.
