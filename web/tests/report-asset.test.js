import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { validateReport } from '../src/report-model.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, 'fixture-report.json');

test('fixture report is valid JSON and matches the report contract', async () => {
  const raw = await readFile(fixturePath, 'utf8');
  const parsed = JSON.parse(raw);

  assert.deepEqual(validateReport(parsed), []);
  assert.match(parsed.reportDate, /^\d{4}-\d{2}-\d{2}$/);
  assert.ok(parsed.stockSignals.length > 0);
  assert.ok(parsed.optionsSignals.length > 0);
});

test('validateReport rejects a report with an empty reportDate', () => {
  const raw = JSON.parse(readFileSync(fixturePath, 'utf8'));
  const errors = validateReport({ ...raw, reportDate: '' });

  assert.ok(errors.some(e => e.includes('reportDate')));
});
