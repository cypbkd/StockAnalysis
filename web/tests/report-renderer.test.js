import test from 'node:test';
import assert from 'node:assert/strict';

import { createEmptyReport } from '../src/report-model.js';
import { renderReportApp, renderSymbolDetail } from '../src/report-renderer.js';

const sampleReport = createEmptyReport({
  reportDate: '2026-04-23',
  generatedAt: '2026-04-23T20:05:00-07:00',
  universe: { name: 'SPY 500', totalSymbols: 503, activeLists: ['SPY 500'] },
  summary: { totalSymbols: 503, matchedSignals: 14, highPrioritySignals: 5, optionsCandidates: 8, earningsWatchCount: 4 },
  highlights: ['S&P breadth at 38.8% — 188 of 484 names in uptrend', 'FANG: 6 of 8 above 20-day'],
  newsSummary: 'NVDA extended its rally on AI demand. AAPL beat earnings expectations.',
  reportHistory: [{ label: 'Apr 23', date: '2026-04-23', href: '/latest/', isActive: true }],
  watchlists: [{ id: 'spy500', name: 'SPY 500', symbols: 503, ruleSummary: '', priority: 'core' }],
  stockSignals: [
    { symbol: 'NVDA', companyName: 'NVIDIA', watchlists: [], ruleNames: [], score: 96, lastPrice: 872.45, changePercent: 2.3, reason: '', status: 'high priority' },
    { symbol: 'XYZ', companyName: 'XYZ Corp', watchlists: [], ruleNames: [], score: 50, lastPrice: 10, changePercent: 0.5, reason: '', status: 'watch' },
  ],
  optionsSignals: [{ symbol: 'AAPL', strategy: 'Bullish call spread', expiration: '2026-04-26', score: 88, reason: '' }],
  earningsWatch: [{ symbol: 'META', companyName: 'Meta Platforms', when: 'After close', priority: 'very high', focus: '' }],
  ruleSets: [{ id: 'core-trend', name: 'Core Trend Rules', universe: 'SPY 500', description: '', naturalLanguage: '' }],
});

test('renderReportApp includes the key dashboard sections', () => {
  const html = renderReportApp(sampleReport);

  assert.match(html, /Analysis Report/);
  assert.match(html, /Today Highlights/);
  assert.match(html, /Top Stock Signals/);
  assert.match(html, /Top Options Ideas/);
  assert.match(html, /Earnings Watch/);
  assert.match(html, /data-section="summary-metrics"/);
  assert.match(html, /data-section="stock-signals"/);
  assert.match(html, /data-section="options-signals"/);
  assert.match(html, /data-section="earnings-watch"/);
  assert.match(html, /Report History/);
  assert.match(html, /history-rail/);
  assert.match(html, /history-link is-active/);
});

test('renderReportApp renders empty states when there are no ideas', () => {
  const html = renderReportApp({
    ...sampleReport,
    stockSignals: [],
    optionsSignals: [],
    earningsWatch: [],
    ruleSets: [],
  });

  assert.match(html, /No high-priority stock signals matched/);
  assert.match(html, /No options ideas matched/);
  assert.match(html, /No earnings events scheduled for this week/);
});

test('renderReportApp renders a scrollable day navigation for historical reports', () => {
  const html = renderReportApp({
    ...sampleReport,
    reportDate: '2026-04-23',
    reportHistory: [
      { label: 'Apr 23', date: '2026-04-23', href: '/latest/', isActive: true },
      { label: 'Apr 22', date: '2026-04-22', href: '/runs/2026-04-22/' },
      { label: 'Apr 21', date: '2026-04-21', href: '/runs/2026-04-21/' },
    ],
  });

  assert.match(html, /aria-label="Report history"/);
  assert.match(html, /href="\/runs\/2026-04-22\/"/);
  assert.match(html, /2026-04-21/);
});

test('renderReportApp uses "Today Highlights" as the Front Page heading', () => {
  const html = renderReportApp(sampleReport);
  assert.match(html, /Today Highlights/);
  assert.doesNotMatch(html, /SPY 500 Coverage/);
});

test('renderReportApp renders newsSummary as the lead paragraph', () => {
  const html = renderReportApp(sampleReport);
  assert.match(html, /NVDA extended its rally on AI demand/);
  assert.match(html, /lead-copy/);
});

test('renderReportApp omits lead paragraph when newsSummary is empty', () => {
  const html = renderReportApp({ ...sampleReport, newsSummary: '' });
  assert.doesNotMatch(html, /lead-copy/);
});

test('renderReportApp renders highlights as bullet list in Front Page section', () => {
  const html = renderReportApp(sampleReport);

  assert.match(html, /front-page-highlights/);
  assert.match(html, /S&amp;P breadth at 38\.8%/);
  assert.match(html, /FANG: 6 of 8 above 20-day/);
});

test('renderReportApp omits highlights list when highlights array is empty', () => {
  const html = renderReportApp({ ...sampleReport, highlights: [] });

  assert.doesNotMatch(html, /front-page-highlights/);
});

test('renderReportApp bulletin ticker shows only high-priority signals with NL descriptions', () => {
  const html = renderReportApp(sampleReport);

  // ticker present and labelled with symbol tag
  assert.match(html, /aria-label="High priority signals"/);
  assert.match(html, /ticker-tag.*NVDA|NVDA.*ticker-tag/s);
  // NL description for NVDA (+2.3%)
  assert.match(html, /NVDA:.*trending higher above key averages/);
  // non-high-priority signal XYZ must not appear in the ticker
  assert.doesNotMatch(html, /ticker-item[\s\S]*XYZ/);
});

test('renderReportApp ticker is absent when no high-priority signals exist', () => {
  const html = renderReportApp({
    ...sampleReport,
    stockSignals: [{ symbol: 'XYZ', companyName: 'XYZ Corp', watchlists: [], ruleNames: [], score: 50, lastPrice: 10, changePercent: 0.5, reason: '', status: 'watch' }],
  });

  assert.doesNotMatch(html, /news-ticker/);
});

test('renderReportApp stock signals section shows only high-priority signals', () => {
  const html = renderReportApp(sampleReport);

  // NVDA is high priority — must appear in stock-signals section
  assert.match(html, /data-section="stock-signals"[\s\S]*NVDA/);
  // XYZ is status "watch" — must not appear in the stock-signals card grid
  // (it may appear in the ticker section but not in the inverted signals section)
  const stockSection = html.match(/data-section="stock-signals"([\s\S]*?)data-section="options-signals"/)?.[1] ?? '';
  assert.doesNotMatch(stockSection, /XYZ Corp/);
});

test('renderReportApp nav order has Earnings before Stocks', () => {
  const html = renderReportApp(sampleReport);

  const earningsPos = html.indexOf('href="#earnings-watch"');
  const stocksPos = html.indexOf('href="#stock-signals"');
  assert.ok(earningsPos < stocksPos, 'Earnings nav link should appear before Stocks nav link');
});

test('renderReportApp Earnings Watch section precedes Top Stock Signals section in HTML', () => {
  const html = renderReportApp(sampleReport);

  const earningsPos = html.indexOf('id="earnings-watch"');
  const stocksPos = html.indexOf('id="stock-signals"');
  assert.ok(earningsPos < stocksPos, 'Earnings Watch section should appear before Top Stock Signals');
});

test('renderReportApp renders earnings chart image when earningsChartUrl is provided', () => {
  const chartUrl = 'https://example.com/earnings-chart.jpg';
  const html = renderReportApp({ ...sampleReport, earningsChartUrl: chartUrl });

  assert.match(html, /earnings-chart/);
  assert.match(html, /src="https:\/\/example\.com\/earnings-chart\.jpg"/);
  assert.match(html, /Earnings Whispers/);
});

test('renderReportApp omits earnings chart when earningsChartUrl is empty', () => {
  const html = renderReportApp({ ...sampleReport, earningsChartUrl: '' });

  assert.doesNotMatch(html, /earnings-chart/);
});

test('renderReportApp signal card links ticker to detail page hash, not Fidelity', () => {
  const html = renderReportApp(sampleReport);

  // high-priority signal NVDA ticker should link to #symbol/NVDA
  assert.match(html, /href="#symbol\/NVDA"/);
  // direct Fidelity link should NOT be used as the ticker anchor
  assert.doesNotMatch(html, /href="https:\/\/digital\.fidelity[^"]*symbol=NVDA"[\s\S]*?NVDA<\/a>/);
});

// ── renderSymbolDetail ────────────────────────────────────────────────────────

const detailReport = createEmptyReport({
  reportDate: '2026-04-23',
  ruleSets: [
    { id: 'ath-breakout', name: 'ATH Breakout', universe: 'SPY 500', description: 'Price breaches 52-week high on elevated volume.', naturalLanguage: 'Flag when close >= high_52w and volume_ratio >= 1.5.' },
    { id: 'high-vol', name: 'High-Volume Momentum Day', universe: 'SPY 500', description: 'Big volume day with momentum confirming direction.', naturalLanguage: 'Flag names with volume at least 2x average.' },
  ],
  stockSignals: [
    {
      symbol: 'NVDA',
      companyName: 'NVIDIA',
      watchlists: ['spy500'],
      ruleNames: ['ATH Breakout', 'High-Volume Momentum Day'],
      score: 100,
      lastPrice: 872.45,
      changePercent: 2.3,
      reason: 'close 872.45 >= 850.00; volume_ratio 2.50 >= 1.50',
      status: 'high priority',
    },
  ],
  optionsSignals: [],
});

test('renderSymbolDetail renders the symbol heading and price', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /NVDA/);
  assert.match(html, /\$872\.45/);
  assert.match(html, /\+2\.3%/);
  assert.match(html, /HIGH PRIORITY/i);
});

test('renderSymbolDetail renders a back link to the root', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /href="#"/);
  assert.match(html, /Back to Report/i);
});

test('renderSymbolDetail renders one card per matched rule name', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /ATH Breakout/);
  assert.match(html, /High-Volume Momentum Day/);
});

test('renderSymbolDetail fills in rule description and naturalLanguage from ruleSets', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /Price breaches 52-week high on elevated volume\./);
  assert.match(html, /Flag when close &gt;= high_52w and volume_ratio &gt;= 1\.5\./);
  assert.match(html, /Big volume day with momentum confirming direction\./);
});

test('renderSymbolDetail parses semicolon-separated reason into individual condition chips', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /close 872\.45 &gt;= 850\.00/);
  assert.match(html, /volume_ratio 2\.50 &gt;= 1\.50/);
  assert.match(html, /condition-item/);
});

test('renderSymbolDetail includes Fidelity chart link for the symbol', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /digital\.fidelity\.com[^"]*NVDA/);
  assert.match(html, /fidelity-link/);
});

test('renderSymbolDetail renders a not-found message for an unknown symbol', () => {
  const html = renderSymbolDetail(detailReport, 'UNKNOWN');

  assert.match(html, /UNKNOWN/);
  assert.match(html, /No signal data found/);
  assert.match(html, /href="#"/);
});

test('renderSymbolDetail handles signals with no reason gracefully', () => {
  const report = createEmptyReport({
    ...detailReport,
    stockSignals: [{ ...detailReport.stockSignals[0], reason: '' }],
  });
  const html = renderSymbolDetail(report, 'NVDA');

  assert.doesNotMatch(html, /condition-item/);
  assert.doesNotMatch(html, /reason-conditions/);
});

test('renderSymbolDetail shows watchlist tags', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /spy500/i);
});
