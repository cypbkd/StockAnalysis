import test from 'node:test';
import assert from 'node:assert/strict';

import { createEmptyReport } from '../src/report-model.js';
import { renderReportApp, renderSymbolDetail, renderDetailAnalysis } from '../src/report-renderer.js';

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
  optionsSignals: [
    { symbol: 'AAPL', strategy: 'Cash-secured put — sell $257 put', expiration: '2026-05-16', score: 85, reason: 'Sell $257 put | Mid $2.45, IV 42%, OI 1,823', highlighted: true },
    { symbol: 'GOOGL', strategy: 'Cash-secured put — sell $327 put', expiration: '2026-05-16', score: 72, reason: 'Sell $327 put | Mid $4.05, IV 40%, OI 987', highlighted: false },
  ],
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

test('renderReportApp options Top Pick badge appears for highlighted signals only', () => {
  const html = renderReportApp(sampleReport);
  assert.match(html, /Top Pick/);
  assert.match(html, /options-highlight/);
  // Non-highlighted card should not get the class
  assert.match(html, /GOOGL/);
  const googSection = html.split('GOOGL')[1] ?? '';
  assert.doesNotMatch(googSection.substring(0, 200), /options-highlight/);
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

const sampleDetailAnalysis = {
  summary: 'NVIDIA is surging on AI infrastructure demand with a powerful confluence of technical signals.',
  rules: [
    { name: 'ATH Breakout', priority: 'High', status: 'triggered', details: 'Close $872.45 >= 52-Week High $872.45 on volume ratio 2.50x' },
    { name: 'High-Volume Momentum Day', priority: 'High', status: 'triggered', details: 'Volume ratio 2.50x >= 2.0x; RSI 68.4 >= 55' },
  ],
  priceTargets: {
    resistance: [
      { label: 'R1 (Pivot)', price: 900.0, note: 'First pivot resistance' },
      { label: 'R2 (Pivot)', price: 930.0, note: 'Extended target' },
    ],
    support: [
      { label: 'S1 (Pivot)', price: 840.0, note: 'First pivot support' },
      { label: 'EMA-20', price: 830.0, note: 'Short-term trend anchor' },
    ],
    entry: { low: 840.0, high: 860.0, note: 'Wait for pullback to S1 pivot area' },
    stopLoss: { price: 810.0, note: 'Below S2 — invalidates breakout thesis' },
  },
  verdict: {
    action: 'Hold / Tactical Buy on Pullback',
    rationale: 'ATH Breakout and High-Volume Momentum Day confirm institutional accumulation.',
    strategy: 'Do not chase above $872. Wait for pullback to $840-$860 S1 zone. Hard stop below $810.',
  },
};

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
      detailAnalysis: sampleDetailAnalysis,
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

test('renderSymbolDetail includes Yahoo Finance chart link for the symbol', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /finance\.yahoo\.com\/quote\/NVDA/);
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

// ── renderSymbolDetail — AI analysis loading placeholder ─────────────────────

test('renderSymbolDetail always renders the AI analysis loading placeholder', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /ai-analysis-placeholder/);
  assert.match(html, /Trading Brief/);
  assert.match(html, /Generating trading brief/);
});

test('renderSymbolDetail placeholder has aria-live for screen readers', () => {
  const html = renderSymbolDetail(detailReport, 'NVDA');

  assert.match(html, /aria-live="polite"/);
});

// ── renderDetailAnalysis ──────────────────────────────────────────────────────

test('renderDetailAnalysis renders summary paragraph', () => {
  const html = renderDetailAnalysis(sampleDetailAnalysis);

  assert.match(html, /NVIDIA is surging on AI infrastructure demand/);
  assert.match(html, /ai-summary/);
});

test('renderDetailAnalysis renders rule scanning table with triggered rules', () => {
  const html = renderDetailAnalysis(sampleDetailAnalysis);

  assert.match(html, /Rule Scanning Status/);
  assert.match(html, /ai-rule-table/);
  assert.match(html, /Close \$872\.45 &gt;= 52-Week High/);
  assert.match(html, /Triggered/);
});

test('renderDetailAnalysis renders price action navigation with resistance and support', () => {
  const html = renderDetailAnalysis(sampleDetailAnalysis);

  assert.match(html, /Price Action Navigation/);
  assert.match(html, /Resistance/i);
  assert.match(html, /Support/i);
  assert.match(html, /\$900\.00/);
  assert.match(html, /\$840\.00/);
});

test('renderDetailAnalysis renders entry zone and stop-loss', () => {
  const html = renderDetailAnalysis(sampleDetailAnalysis);

  assert.match(html, /Entry \/ Exit/i);
  assert.match(html, /\$840\.00/);
  assert.match(html, /\$860\.00/);
  assert.match(html, /\$810\.00/);
  assert.match(html, /price-level-stop/);
});

test('renderDetailAnalysis renders final trading verdict with action badge', () => {
  const html = renderDetailAnalysis(sampleDetailAnalysis);

  assert.match(html, /Final Trading Verdict/);
  assert.match(html, /Hold \/ Tactical Buy on Pullback/);
  assert.match(html, /ai-verdict-action/);
  assert.match(html, /institutional accumulation/);
  assert.match(html, /ai-strategy/);
});

test('renderDetailAnalysis returns empty string for null/undefined', () => {
  assert.strictEqual(renderDetailAnalysis(null), '');
  assert.strictEqual(renderDetailAnalysis(undefined), '');
});

test('renderDetailAnalysis omits rule table when rules array is empty', () => {
  const html = renderDetailAnalysis({ ...sampleDetailAnalysis, rules: [] });

  assert.doesNotMatch(html, /ai-rule-table/);
  assert.match(html, /ai-summary/);
});

test('renderDetailAnalysis renders fundamentals when present', () => {
  const analysis = {
    ...sampleDetailAnalysis,
    fundamentals: { pe: 42.3, forwardPe: 31.8, eps: 8.22, fairPrice: 621.68, bondYield: 4.7 },
  };
  const html = renderDetailAnalysis(analysis);
  assert.match(html, /fund-grid/);
  assert.match(html, /P\/E \(TTM\)/);
  assert.match(html, /Forward P\/E/);
  assert.match(html, /Graham Fair Value/);
  assert.match(html, /621/);
  assert.match(html, /4\.4\/Y/);
  assert.match(html, /4\.7%/);
});

test('renderDetailAnalysis omits fundamentals block when absent', () => {
  const html = renderDetailAnalysis(sampleDetailAnalysis);
  assert.doesNotMatch(html, /ai-fundamentals/);
});

// ── renderSymbolDetail — earnings badge ───────────────────────────────────────

const detailReportWithTechData = createEmptyReport({
  reportDate: '2026-04-23',
  stockSignals: [
    {
      symbol: 'NVDA',
      companyName: 'NVIDIA',
      watchlists: ['spy500'],
      ruleNames: ['ATH Breakout'],
      score: 100,
      lastPrice: 872.45,
      changePercent: 2.3,
      reason: 'close 872.45 >= 850.00',
      status: 'high priority',
      technicalData: {
        sessionOpen: 855.0,
        sessionHigh: 880.0,
        sessionLow: 850.0,
        prevOpen: 840.0,
        prevClose: 845.0,
        prevHigh: 862.0,
        prevLow: 835.0,
        volumeRatio: 2.11,
        rsi14: 68.4,
        ema20: 830.0,
        sma20: 825.0,
        sma50: 780.0,
        sma200: 620.0,
        high52w: 872.45,
        low52w: 400.0,
        pivotPoint: 854.0,
        pivotR1: 900.0,
        pivotR2: 930.0,
        pivotS1: 840.0,
        pivotS2: 810.0,
        high200d: 872.45,
        low200d: 400.0,
        ltR1: 1100.0,
        ltR2: 1380.0,
        ltS1: 350.0,
        ltS2: 70.0,
        earningsDate: '2026-04-26',
        earningsInDays: 3,
        earningsTiming: 'After Close',
      },
    },
  ],
});

test('renderSymbolDetail shows earnings badge when within 7 days', () => {
  const html = renderSymbolDetail(detailReportWithTechData, 'NVDA');
  assert.match(html, /earnings-badge/);
  assert.match(html, /Earnings in 3d/);
  assert.match(html, /After Close/);
});

test('renderSymbolDetail does not show earnings badge when outside 7-day window', () => {
  const report = createEmptyReport({
    reportDate: '2026-04-23',
    stockSignals: [
      {
        symbol: 'NVDA',
        companyName: 'NVIDIA',
        watchlists: [],
        ruleNames: [],
        score: 100,
        lastPrice: 800.0,
        changePercent: 0,
        reason: '',
        status: 'matched',
        technicalData: { earningsDate: '2026-06-01', earningsInDays: 40 },
      },
    ],
  });
  const html = renderSymbolDetail(report, 'NVDA');
  assert.doesNotMatch(html, /earnings-badge/);
});

test('renderSymbolDetail renders long-term S/R section when ltR1 is present', () => {
  const html = renderSymbolDetail(detailReportWithTechData, 'NVDA');
  assert.match(html, /lt-levels-section/);
  assert.match(html, /200-Day S\/R Map/);
  assert.match(html, /LT Pivots/);
  assert.match(html, /200-Day Range/);
});

test('renderSymbolDetail renders short-term daily session section when session data present', () => {
  const reportWithSession = createEmptyReport({
    reportDate: '2026-04-23',
    stockSignals: [{
      symbol: 'NVDA',
      companyName: 'NVIDIA',
      watchlists: [],
      ruleNames: [],
      score: 100,
      lastPrice: 872.45,
      changePercent: 2.3,
      reason: '',
      status: 'high priority',
      technicalData: {
        sessionOpen: 850.0,
        sessionHigh: 880.0,
        sessionLow: 845.0,
        prevClose: 840.0,
        prevOpen: 835.0,
        prevHigh: 855.0,
        prevLow: 830.0,
        pivotPoint: 845.0,
        pivotR1: 900.0,
        pivotR2: 930.0,
        pivotS1: 840.0,
        pivotS2: 810.0,
        ltR1: 1100.0,
        ltS1: 350.0,
        sma200: 620.0,
      },
    }],
  });
  const html = renderSymbolDetail(reportWithSession, 'NVDA');
  assert.match(html, /Daily Session.*Pivot Levels/s);
  assert.match(html, /Today/);
  assert.match(html, /Previous Day/);
  assert.match(html, /Pivots/);
  // Today column shows lastPrice as Close
  assert.match(html, /872\.45/);
  // Pivot labels are compact
  assert.match(html, /\bR1\b/);
  assert.match(html, /\bS2\b/);
});

test('renderSymbolDetail renders TradingView chart container with symbol', () => {
  const html = renderSymbolDetail(detailReportWithTechData, 'NVDA');
  assert.match(html, /tradingview-chart-container/);
  assert.match(html, /data-symbol="NVDA"/);
});

test('renderReportApp date-only reportDate displays the correct calendar day (no UTC midnight shift)', () => {
  // "2026-04-29" must render as "April 29" not "April 28" in negative-offset timezones
  const html = renderReportApp({ ...sampleReport, reportDate: '2026-04-29' });
  assert.match(html, /April 29, 2026/);
  assert.doesNotMatch(html, /April 28, 2026/);
});

test('renderEarningsCalendar marks only the report-date day tickers as ec-priority-very-high', () => {
  const report = createEmptyReport({
    reportDate: '2026-04-29',
    earningsWatch: [
      { symbol: 'MON', companyName: 'Monday Co', date: '2026-04-27', weekday: 'Monday', timing: 'TBD', priority: 'very high', when: 'In 0 days', focus: '' },
      { symbol: 'WED', companyName: 'Wednesday Co', date: '2026-04-29', weekday: 'Wednesday', timing: 'TBD', priority: 'very high', when: 'Today', focus: '' },
      { symbol: 'THU', companyName: 'Thursday Co', date: '2026-04-30', weekday: 'Thursday', timing: 'TBD', priority: 'very high', when: 'Tomorrow', focus: '' },
    ],
  });
  const html = renderReportApp(report);

  // Wednesday (today) ticker's li must carry ec-priority-very-high directly before the WED link
  assert.match(html, /ec-ticker-item ec-priority-very-high[^>]*>[\s\S]{0,200}?ec-symbol[^>]*>WED/);
  // Monday and Thursday tickers must not have ec-priority-very-high on their li
  assert.doesNotMatch(html, /ec-ticker-item ec-priority-very-high[^>]*>[\s\S]{0,200}?ec-symbol[^>]*>MON/);
  assert.doesNotMatch(html, /ec-ticker-item ec-priority-very-high[^>]*>[\s\S]{0,200}?ec-symbol[^>]*>THU/);
  // Wednesday column header must carry ec-day-today; Monday and Thursday must not
  assert.match(html, /ec-day-col[^"]*ec-day-today[^>]*>[\s\S]{0,100}?ec-day-header[^>]*>Wednesday/);
  assert.doesNotMatch(html, /ec-day-col[^"]*ec-day-today[^>]*>[\s\S]{0,100}?ec-day-header[^>]*>Monday/);
  assert.doesNotMatch(html, /ec-day-col[^"]*ec-day-today[^>]*>[\s\S]{0,100}?ec-day-header[^>]*>Thursday/);
});
