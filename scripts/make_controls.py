"""Construct sensitivity fixtures; NONE of these are real project defects."""
from pathlib import Path
import json
from datetime import datetime, timezone
from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'data/controls'
S = '%(name)s has %(n)d item'
P = '%(name)s has %(n)d items'
C = '%(n)d item'
D = '%(n)d items'
CASES=[]

def case(key, locale, ids, translations, body, category='legitimate', note='', flags=('python-format',), expected_error_counts=None, expected_unknown=False, contains=None, context=None):
    directory=FOLDER/key
    directory.mkdir(parents=True,exist_ok=True)
    source='def message(n: int):\n'+''.join('    '+line+'\n' for line in body.splitlines())
    (directory/'call.py').write_text(source)
    catalog=Catalog(locale=locale,domain='controls',project='MsgBranch constructed controls',version='0.1',copyright_holder='MsgBranch contributors',creation_date=datetime(2026,9,30,tzinfo=timezone.utc),revision_date=datetime(2026,9,30,tzinfo=timezone.utc))
    if ids is not None:
        catalog.add(ids,translations,flags=flags,context=context)
    with (directory/'messages.po').open('wb') as fp:
        write_po(fp,catalog,width=88,omit_header=False)
    CASES.append({'id':key,'locale':locale,'category':category,'note':note,'source':f'data/controls/{key}/call.py','catalog':f'data/controls/{key}/messages.po',
                  'expected_error_counts':expected_error_counts or [],'expected_unknown':expected_unknown,'contains':contains})

case('reorder','en',(S,P),('One item for %(name)s: %(n)d','%(n)d items for %(name)s'),f'msg = ngettext({S!r}, {P!r}, n)\nreturn msg % {{"name": "Ada", "n": n}}',note='Named arguments are reordered, never rewritten by MsgBranch.')
case('omit-singular-count','en',(S,P),('One item for %(name)s','%(n)d items for %(name)s'),f'msg = ngettext({S!r}, {P!r}, n)\nreturn msg % {{"name": "Ada", "n": n}}',note='In the sole n=1 branch, the count is intentionally implicit.')
case('omit-optional-owner','en',(S,P),('%(n)d item','%(n)d items'),f'msg = ngettext({S!r}, {P!r}, n)\nreturn msg % {{"name": "Ada", "n": n}}',note='Constructed application contract permits owner omission; no linguistic quality assertion.')
case('branch-specific-args','en',('One item',D),('One item',D),f'msg = ngettext("One item", {D!r}, n)\nargs = {{}} if n == 1 else {{"n": n}}\nreturn msg % args',note='Singular needs no mapping key; union-of-branches would overrequire n.')
case('japanese-one-form','ja',('One item',D),('%(n)d items',),f'msg = ngettext("One item", {D!r}, n)\nreturn msg % {{"n": n}}',note='One locale form, including n=1, uses count. English singular omits it.')
case('russian-three-form','ru',(C,D),('%(n)d item [one]','%(n)d items [few]','%(n)d items [many]'),f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',note='Artificial labels identify actual gettext formula indexes, not translated prose.')
case('arabic-six-form','ar',(C,D),tuple('%(n)d items ['+x+']' for x in ['zero','one','two','few','many','other']),f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',note='Actual Babel header formula; category names are labels only.')
case('intended-fallback','en',None,None,f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',note='No translation supplied; the constructed application explicitly permits source fallback.')
case('brace-reorder','en','{name} has {n:d} items','{n:d} items for {name}', 'msg = gettext("{name} has {n:d} items")\nreturn msg.format(name="Ada", n=n)',flags=('python-brace-format',),note='Separate Python brace interpolation, not Fluent.')
case('extra-unused-arg','en',(C,D),(C,D),f'return ngettext({C!r}, {D!r}, n) % {{"n": n, "unused": "ok"}}',note='Providing an unused mapping key is legal.')
case('missing-always','en',(S,P),(S,P),f'return ngettext({S!r}, {P!r}, n) % {{"n": n}}',category='mutation',note='Remove name from the supplying mapping.',expected_error_counts=list(range(201)))
case('missing-at-100','en',(C,D),(C,D),f'msg = ngettext({C!r}, {D!r}, n)\nargs = {{}} if n == 100 else {{"n": n}}\nreturn msg % args',category='mutation',note='Remove n only at a declared application boundary; ordinary samples miss it.',expected_error_counts=[100])
case('type-at-100','en',(C,D),(C,D),f'msg = ngettext({C!r}, {D!r}, n)\nvalue = str(n) if n == 100 else n\nreturn msg % {{"n": value}}',category='mutation',note='Supply a string for %d only at n=100.',expected_error_counts=[100])
case('translation-new-key','en',(C,D),(C,'%(missing)d items'),f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',category='mutation',note='Ordinary catalog linter duplicate; explicitly retained.',expected_error_counts=[n for n in range(201) if n!=1])
case('arabic-zero-key','ar',(C,D),('%(missing)d zero','%(n)d one','%(n)d two','%(n)d few','%(n)d many','%(n)d other'),f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',category='mutation',note='A catalog mutation on the zero branch, not a discovered Arabic translation bug.',expected_error_counts=[0])
case('brace-missing','en','{name} has {n:d} items','{n:d} items for {name}','msg = gettext("{name} has {n:d} items")\nreturn msg.format(n=n)',category='mutation',flags=('python-brace-format',),expected_error_counts=list(range(201)),note='Missing keyword in an otherwise valid brace-format catalog.')
case('wrong-dialect','en',(C,D),(C,D),f'msg = ngettext({C!r}, {D!r}, n)\nreturn msg.format(n=n)',category='mutation',note='Pattern inspired by a test-only repair; expected rendering obligation is explicit, not inferred from nonemptiness.',contains='count',expected_error_counts=[])
case('compiler-empty-plural','en',(C,D),('',D),f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',note='Babel replaces the empty singular plural slot while writing MO; fallback provenance must survive compilation.')
case('fuzzy-fallback','en',(C,D),(C,D),f'return ngettext({C!r}, {D!r}, n) % {{"n": n}}',flags=('python-format','fuzzy'),note='Fuzzy translation is omitted at compilation; source fallback is intended.')
case('dynamic-key','en',(C,D),(C,D),f'key = {C!r} if n == 1 else {D!r}\nreturn gettext(key) % {{"n": n}}',category='unknown',expected_unknown=True,note='Even finite dynamic identifier is outside literal-ID adapter; never silently passed.')
case('dynamic-supplier','en',(C,D),(C,D),f'return ngettext({C!r}, {D!r}, n) % make_args(n)',category='unknown',expected_unknown=True,note='Unresolved external mapping supplier is unknown.')
case('percent-char-int','en','%c item','%c item','return gettext("%c item") % n',note='Percent %c accepts an integer code point; primitive type recovery must not reject it.')
case('context-singular','fr','Open','Ouvrir','return pgettext("menu", "Open")',flags=(),context='menu',note='Contextual singular lookup is selected through GNUTranslations.pgettext.')
case('context-plural','fr',(C,D),('%(n)d fichier','%(n)d fichiers'),f'return npgettext("files", {C!r}, {D!r}, n) % {{"n": n}}',context='files',note='Contextual plural lookup retains branch-specific percent requirements.')
case('nested-brace-format','en','{value:.{precision}f}','{value:.{precision}f}','return gettext("{value:.{precision}f}").format(value=1.25, precision=2)',flags=('python-brace-format',),note='Nested format-spec fields are recovered without treating the translation as prose.')
(ROOT/'data/control-manifest.json').write_text(json.dumps(CASES,indent=2)+'\n')
print(f'Wrote {len(CASES)} constructed families')
