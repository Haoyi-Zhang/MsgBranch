/**
 * Source excerpt copied verbatim from localheroai/cli at commit
 * af81321af193458f5869befec4481b8507c2d78d. See PROVENANCE.md and LICENSE.
 */
const PLACEHOLDER_PATTERN =
  /(%%)|\{\{\s*-?\s*([\w.]+)\s*(?:,[^}]*)?\}\}|%<([\w.]+)>[sdf]|%\{([\w.]+)\}|%\(([\w.]+)\)[sdf]|%(\d+)\$([sdfiugx])|(?<!\d)%([sdfiugx])|\{([\w.]+)\}/g;

export type PlaceholderKind =
  | 'i18next'
  | 'icu'
  | 'rails-typed'
  | 'rails'
  | 'python'
  | 'positional'
  | 'printf';

export interface Placeholder {
  kind: PlaceholderKind;
  name: string;
}

const ICU_COMPLEX_START = /\{\s*([\w.]+)\s*,\s*(plural|select|selectordinal)\s*,/g;
const MAX_ICU_REDUCTIONS = 20;

export function reduceIcuComplexArguments(text: string): string {
  let result = text;
  for (let pass = 0; pass < MAX_ICU_REDUCTIONS; pass++) {
    ICU_COMPLEX_START.lastIndex = 0;
    const match = ICU_COMPLEX_START.exec(result);
    if (!match) break;
    const end = matchingBrace(result, match.index);
    if (end === -1) break;
    result = `${result.slice(0, match.index)}{${match[1]}}${result.slice(end + 1)}`;
  }
  return result;
}

function matchingBrace(text: string, start: number): number {
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}' && --depth === 0) return i;
  }
  return -1;
}

export function extractPlaceholders(text: string): Placeholder[] {
  if (typeof text !== 'string') return [];
  const found: Placeholder[] = [];
  for (const match of reduceIcuComplexArguments(text).matchAll(PLACEHOLDER_PATTERN)) {
    const [full, escaped, i18next, railsTyped, rails, python, , positionalType, printf, icu] = match;
    if (escaped) continue;
    const name = i18next ?? railsTyped ?? rails ?? python ?? positionalType ?? printf ?? icu;
    found.push({ kind: classify(full), name });
  }
  return found;
}

function classify(full: string): PlaceholderKind {
  if (full.startsWith('{{')) return 'i18next';
  if (full.startsWith('{')) return 'icu';
  if (full.startsWith('%<')) return 'rails-typed';
  if (full.startsWith('%{')) return 'rails';
  if (full.startsWith('%(')) return 'python';
  if (/^%\d/.test(full)) return 'positional';
  return 'printf';
}

function token(placeholder: Placeholder): string {
  if (placeholder.kind === 'positional') return `printf:${placeholder.name}`;
  return `${placeholder.kind}:${placeholder.name}`;
}

const STRFTIME_DIRECTIVE = /%[-_0^#]?[aAbBCDFGhHIjklLmMnNpPrRSTUVwWXyYzZ]/;

export function isStrftimeFormat(text: string): boolean {
  return STRFTIME_DIRECTIVE.test(text.replace(/%%/g, ''));
}

export function placeholderMultiset(text: string): Map<string, number> {
  const counts = new Map<string, number>();
  for (const placeholder of extractPlaceholders(text)) {
    const key = token(placeholder);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}
