import test from 'node:test';
import assert from 'node:assert/strict';

import { createEmptyReport, validateReport } from '../src/report-model.js';

test('validateReport accepts a valid report and rejects malformed input', () => {
  const valid = createEmptyReport({ reportDate: '2026-04-23' });
  assert.deepEqual(validateReport(valid), []);
  assert.match(validateReport({}).join('\n'), /reportDate/);
});

test('createEmptyReport produces a normalized scaffold', () => {
  const report = createEmptyReport();

  assert.equal(report.reportLabel, 'Nightly Stock Analysis Report');
  assert.equal(report.summary.totalSymbols, 0);
  assert.deepEqual(report.highlights, []);
  assert.equal(report.newsSummary, '');
  assert.equal(report.earningsChartUrl, '');
  assert.deepEqual(report.watchlists, []);
  assert.deepEqual(report.stockSignals, []);
  assert.deepEqual(report.optionsSignals, []);
  assert.deepEqual(report.earningsWatch, []);
  assert.deepEqual(report.ruleSets, []);
});
