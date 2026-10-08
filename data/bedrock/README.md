# Bedrock upstream boundary control

Seven existing assertions from `TestFluentTranslationUtils.test_translate` and
`test_translate_term_fallback` are replayed through the extracted application
boundary and a pinned native Fluent runtime. Five complete upstream FTL files are
byte-verified by Git blob identity. These are normal behaviors, not defects or
production observations. The original English wording and language labels are
kept unchanged; they are upstream test fixtures, not linguistic evaluations.

The selected Bedrock methods retain their logic; `functools.cached_property`
replaces Django's decorator. The loader replaces settings/cache wiring with a
local root and retains resource/English-brand insertion order. No Django
application, HTTP route, or upstream full test suite is claimed. MPL-2.0 applies
to the retained source and fixtures; see their original notices and provenance.
