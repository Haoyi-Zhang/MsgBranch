# OpenHangar historical boundary reconstruction

One fix is the defect unit. Two locales and two equivalent template expressions
are repeated contexts, NOT four independently discovered defects. The archived
upstream repair identifies a shared singular message ID whose two supplying calls
use different plural argument names. Catalog checking sees only the merged entry.
A simple call/plural-text consistency check and ordinary n=1,2 rendering tests can
also detect the issue. No incremental real-defect yield over these is claimed.

See PROVENANCE.json for exact source identities, header/entry excerpts and all
substitutions. Run `python scripts/openhangar_boundary.py` from the artifact root.
The native comparison executes Jinja2's newstyle i18n component, not a complete
historical Flask-Babel application. No application service is started.
