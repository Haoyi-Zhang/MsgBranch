import fs from 'node:fs';
import { findPlaceholderMismatches } from './dist/check-utils.js';

const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = input.map((row) => {
  const findings = findPlaceholderMismatches(row.source, row.target);
  return {
    ...row.meta,
    error: findings.some((finding) => !finding.hint),
    hint: findings.some((finding) => Boolean(finding.hint)),
    findings
  };
});
fs.writeFileSync(process.argv[3], JSON.stringify(output, null, 2) + '\n');
