"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.reduceIcuComplexArguments = reduceIcuComplexArguments;
exports.extractPlaceholders = extractPlaceholders;
exports.isStrftimeFormat = isStrftimeFormat;
exports.placeholderMultiset = placeholderMultiset;
/**
 * Source excerpt copied verbatim from localheroai/cli at commit
 * af81321af193458f5869befec4481b8507c2d78d. See PROVENANCE.md and LICENSE.
 */
const PLACEHOLDER_PATTERN = /(%%)|\{\{\s*-?\s*([\w.]+)\s*(?:,[^}]*)?\}\}|%<([\w.]+)>[sdf]|%\{([\w.]+)\}|%\(([\w.]+)\)[sdf]|%(\d+)\$([sdfiugx])|(?<!\d)%([sdfiugx])|\{([\w.]+)\}/g;
const ICU_COMPLEX_START = /\{\s*([\w.]+)\s*,\s*(plural|select|selectordinal)\s*,/g;
const MAX_ICU_REDUCTIONS = 20;
function reduceIcuComplexArguments(text) {
    let result = text;
    for (let pass = 0; pass < MAX_ICU_REDUCTIONS; pass++) {
        ICU_COMPLEX_START.lastIndex = 0;
        const match = ICU_COMPLEX_START.exec(result);
        if (!match)
            break;
        const end = matchingBrace(result, match.index);
        if (end === -1)
            break;
        result = `${result.slice(0, match.index)}{${match[1]}}${result.slice(end + 1)}`;
    }
    return result;
}
function matchingBrace(text, start) {
    let depth = 0;
    for (let i = start; i < text.length; i++) {
        if (text[i] === '{')
            depth++;
        else if (text[i] === '}' && --depth === 0)
            return i;
    }
    return -1;
}
function extractPlaceholders(text) {
    if (typeof text !== 'string')
        return [];
    const found = [];
    for (const match of reduceIcuComplexArguments(text).matchAll(PLACEHOLDER_PATTERN)) {
        const [full, escaped, i18next, railsTyped, rails, python, , positionalType, printf, icu] = match;
        if (escaped)
            continue;
        const name = i18next ?? railsTyped ?? rails ?? python ?? positionalType ?? printf ?? icu;
        found.push({ kind: classify(full), name });
    }
    return found;
}
function classify(full) {
    if (full.startsWith('{{'))
        return 'i18next';
    if (full.startsWith('{'))
        return 'icu';
    if (full.startsWith('%<'))
        return 'rails-typed';
    if (full.startsWith('%{'))
        return 'rails';
    if (full.startsWith('%('))
        return 'python';
    if (/^%\d/.test(full))
        return 'positional';
    return 'printf';
}
function token(placeholder) {
    if (placeholder.kind === 'positional')
        return `printf:${placeholder.name}`;
    return `${placeholder.kind}:${placeholder.name}`;
}
const STRFTIME_DIRECTIVE = /%[-_0^#]?[aAbBCDFGhHIjklLmMnNpPrRSTUVwWXyYzZ]/;
function isStrftimeFormat(text) {
    return STRFTIME_DIRECTIVE.test(text.replace(/%%/g, ''));
}
function placeholderMultiset(text) {
    const counts = new Map();
    for (const placeholder of extractPlaceholders(text)) {
        const key = token(placeholder);
        counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
}
