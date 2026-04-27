import { renderReportApp, renderSymbolDetail, renderDetailAnalysis } from './report-renderer.js';

function reportUrl() {
  const date = new URLSearchParams(window.location.search).get('date');
  return date
    ? `./reports/runs/${date}/report.json`
    : './reports/latest/report.json';
}

async function loadReport() {
  try {
    const response = await fetch(reportUrl(), { cache: 'no-store' });
    if (!response.ok) {
      return null;
    }
    return await response.json();
  } catch {
    return null;
  }
}

async function loadConfig() {
  try {
    const response = await fetch('./config.json', { cache: 'no-store' });
    if (!response.ok) return {};
    return await response.json();
  } catch {
    return {};
  }
}

function getSymbolFromHash() {
  const hash = window.location.hash;
  const match = hash.match(/^#symbol\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function loadAndRenderAnalysis(symbol, reportDate, analysisUrl) {
  const placeholder = document.getElementById('ai-analysis-placeholder');
  if (!placeholder) return;

  if (!analysisUrl) {
    placeholder.outerHTML = '';
    return;
  }

  try {
    const url = `${analysisUrl}?ticker=${encodeURIComponent(symbol)}&date=${encodeURIComponent(reportDate || '')}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const analysis = await response.json();
    if (analysis.error) throw new Error(analysis.error);
    placeholder.outerHTML = renderDetailAnalysis(analysis);
  } catch (err) {
    const el = document.getElementById('ai-analysis-placeholder');
    if (el) el.outerHTML = '';
  }
}

function applyView(report, config) {
  const root = document.querySelector('#app');
  if (!root) return;

  if (!report) {
    document.title = 'Stock Analysis';
    root.innerHTML = '<p class="unavailable">The data is not available.</p>';
    return;
  }

  const symbol = getSymbolFromHash();

  if (symbol) {
    document.title = `${symbol} — Signal Detail`;
    root.innerHTML = renderSymbolDetail(report, symbol);
    window.scrollTo(0, 0);
    loadAndRenderAnalysis(symbol, report.reportDate, config?.analysisUrl);
    return;
  }

  const dateLabel = report.reportDate
    ? new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(new Date(report.reportDate))
    : 'Latest';
  document.title = `${dateLabel} Analysis Report`;
  root.innerHTML = renderReportApp(report);
}

let cachedReport = null;
let cachedConfig = {};

async function bootstrap() {
  [cachedReport, cachedConfig] = await Promise.all([loadReport(), loadConfig()]);
  applyView(cachedReport, cachedConfig);
}

window.addEventListener('hashchange', () => {
  applyView(cachedReport, cachedConfig);
});

bootstrap();
