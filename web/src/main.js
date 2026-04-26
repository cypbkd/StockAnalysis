import { renderReportApp, renderSymbolDetail } from './report-renderer.js';

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

function getSymbolFromHash() {
  const hash = window.location.hash;
  const match = hash.match(/^#symbol\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function applyView(report) {
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
    return;
  }

  const dateLabel = report.reportDate
    ? new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(new Date(report.reportDate))
    : 'Latest';
  document.title = `${dateLabel} Analysis Report`;
  root.innerHTML = renderReportApp(report);
}

let cachedReport = null;

async function bootstrap() {
  cachedReport = await loadReport();
  applyView(cachedReport);
}

window.addEventListener('hashchange', () => {
  applyView(cachedReport);
});

bootstrap();
