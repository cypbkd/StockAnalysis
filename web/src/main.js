import { renderReportApp, renderSymbolDetail, renderDetailAnalysis, renderComplianceDetail } from './report-renderer.js';

function injectTradingViewChart(symbol) {
  const container = document.getElementById('tradingview-chart-container');
  if (!container) return;

  const inner = container.querySelector('.tv-chart-inner');
  if (!inner) return;

  // TradingView advanced chart widget — supports candle charts via style:"1"
  // Script tags in innerHTML don't execute; we create and append the script node dynamically.
  const script = document.createElement('script');
  script.type = 'text/javascript';
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.async = true;
  script.textContent = JSON.stringify({
    autosize: true,
    symbol: symbol,
    interval: 'D',
    timezone: 'America/New_York',
    theme: 'light',
    style: '1',
    locale: 'en',
    withdateranges: true,
    range: '12M',
    hide_side_toolbar: true,
    allow_symbol_change: false,
    save_image: false,
    calendar: false,
    studies: [
      { id: 'MASimple@tv-basicstudies', inputs: { length: 5 } },
      { id: 'MASimple@tv-basicstudies', inputs: { length: 20 } },
      { id: 'MASimple@tv-basicstudies', inputs: { length: 200 } },
    ],
  });

  inner.appendChild(script);
}

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

function _applyLiveMetrics(liveMetrics) {
  if (!liveMetrics) return;
  const { price, change } = liveMetrics;

  if (price != null) {
    const priceEl = document.querySelector('.detail-price');
    if (priceEl) {
      priceEl.textContent = new Intl.NumberFormat('en-US', {
        style: 'currency', currency: 'USD', maximumFractionDigits: 2,
      }).format(price);
    }
  }

  if (change != null) {
    const changeEl = document.querySelector('.detail-change');
    if (changeEl) {
      const prefix = change > 0 ? '+' : '';
      changeEl.textContent = `${prefix}${change.toFixed(1)}%`;
      changeEl.className = `detail-change ${change >= 0 ? 'is-positive' : 'is-negative'}`;
    }
  }
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
    _applyLiveMetrics(analysis.liveMetrics);
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
    injectTradingViewChart(symbol);
    loadAndRenderAnalysis(symbol, report.reportDate, config?.analysisUrl);
    return;
  }

  const dateLabel = report.reportDate
    ? new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(new Date(report.reportDate + 'T12:00:00'))
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

// Compliance detail toggle — called by onclick in the compliance table rows
const _complianceDetailCache = {};
window.toggleComplianceDetail = async function toggleComplianceDetail(ticker) {
  const rowId = `cd-row-${ticker}`;
  const detailRow = document.getElementById(rowId);
  if (!detailRow) return;

  const btn = detailRow.previousElementSibling?.querySelector('.cd-expand-btn');
  const isOpen = !detailRow.hidden;

  if (isOpen) {
    detailRow.hidden = true;
    if (btn) { btn.textContent = '▶'; btn.setAttribute('aria-expanded', 'false'); }
    return;
  }

  detailRow.hidden = false;
  if (btn) { btn.textContent = '▼'; btn.setAttribute('aria-expanded', 'true'); }

  if (_complianceDetailCache[ticker]) {
    detailRow.querySelector('.cd-detail-inner').innerHTML = renderComplianceDetail(_complianceDetailCache[ticker]);
    return;
  }

  try {
    const res = await fetch(`./evaluations/tickers/${encodeURIComponent(ticker)}.json`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const detail = await res.json();
    _complianceDetailCache[ticker] = detail;
    detailRow.querySelector('.cd-detail-inner').innerHTML = renderComplianceDetail(detail);
  } catch {
    detailRow.querySelector('.cd-detail-inner').innerHTML = `<p class="empty-state">Could not load detail for ${ticker}.</p>`;
  }
};

bootstrap();
