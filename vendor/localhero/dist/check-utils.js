"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.toStringValue = toStringValue;
exports.findPlaceholderMismatches = findPlaceholderMismatches;
/**
 * Placeholder-mismatch component excerpt copied from localheroai/cli at
 * commit af81321af193458f5869befec4481b8507c2d78d. Unrelated check-command
 * functions are omitted. See PROVENANCE.md and LICENSE.
 */
const placeholders_js_1 = require("./placeholders.js");
function toStringValue(entry) {
    if (entry === null || entry === undefined)
        return null;
    if (typeof entry === 'string')
        return entry;
    if (typeof entry === 'number' || typeof entry === 'boolean')
        return String(entry);
    if (Array.isArray(entry))
        return null;
    if (typeof entry === 'object' && 'value' in entry)
        return toStringValue(entry.value);
    return null;
}
function findPlaceholderMismatches(sourceKeys, targetKeys) {
    const mismatches = [];
    const pluralBases = gettextPluralBases([...Object.keys(sourceKeys), ...Object.keys(targetKeys)]);
    for (const key of Object.keys(sourceKeys)) {
        const source = toStringValue(sourceKeys[key]);
        if (source === null || source === '')
            continue;
        const target = toStringValue(targetKeys[key]);
        if (target === null || target === '')
            continue;
        if ((0, placeholders_js_1.isStrftimeFormat)(source) || (0, placeholders_js_1.isStrftimeFormat)(target))
            continue;
        const sourceCounts = (0, placeholders_js_1.placeholderMultiset)(source);
        const targetCounts = (0, placeholders_js_1.placeholderMultiset)(target);
        if (sourceCounts.size === 0 && targetCounts.size === 0)
            continue;
        const missingInTarget = [];
        const unexpectedInTarget = [];
        for (const [token, count] of sourceCounts) {
            if ((targetCounts.get(token) ?? 0) < count)
                missingInTarget.push(token);
        }
        const pluralForm = isPluralFormKey(key) || pluralBases.has(key);
        for (const [token, count] of targetCounts) {
            if (pluralForm && token.endsWith(':count'))
                continue;
            if ((sourceCounts.get(token) ?? 0) < count)
                unexpectedInTarget.push(token);
        }
        if (missingInTarget.length === 0 && unexpectedInTarget.length === 0)
            continue;
        const omissionInPluralForm = unexpectedInTarget.length === 0 && (mayOmitPlaceholder(key) || pluralBases.has(key));
        mismatches.push({
            key,
            source,
            target,
            missingInTarget,
            unexpectedInTarget,
            ...(omissionInPluralForm ? { hint: true } : {})
        });
    }
    return mismatches;
}
const GETTEXT_PLURAL_SUFFIX = /__plural_\d+$/;
const COUNT_OPTIONAL_CATEGORIES = ['zero', 'one', 'two'];
const RAILS_PLURAL_LEAVES = new Set(['zero', 'one', 'two', 'few', 'many', 'other']);
const I18NEXT_PLURAL_SUFFIXES = ['_zero', '_one', '_two', '_few', '_many', '_other', '_plural'];
function leafOf(key) {
    return key.slice(key.lastIndexOf('.') + 1);
}
function isPluralFormKey(key) {
    if (GETTEXT_PLURAL_SUFFIX.test(key))
        return true;
    const leaf = leafOf(key);
    return RAILS_PLURAL_LEAVES.has(leaf) || I18NEXT_PLURAL_SUFFIXES.some((suffix) => leaf.endsWith(suffix));
}
function mayOmitPlaceholder(key) {
    if (GETTEXT_PLURAL_SUFFIX.test(key))
        return true;
    const leaf = leafOf(key);
    return COUNT_OPTIONAL_CATEGORIES.some((category) => leaf === category || leaf.endsWith(`_${category}`));
}
function gettextPluralBases(keys) {
    const bases = new Set();
    for (const key of keys) {
        if (GETTEXT_PLURAL_SUFFIX.test(key))
            bases.add(key.replace(GETTEXT_PLURAL_SUFFIX, ''));
    }
    return bases;
}
