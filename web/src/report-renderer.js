import { createEmptyReport, validateReport } from './report-model.js';

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatPrice(value) {
  if (!Number.isFinite(value)) {
    return 'n/a';
  }

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value) {
  if (!Number.isFinite(value)) {
    return 'n/a';
  }

  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(1)}%`;
}

function sanitizeIso(value) {
  // Fix malformed ISO like "2026-04-25T04:01:37+00:00Z" (redundant Z after offset)
  return typeof value === 'string' ? value.replace(/([+-]\d{2}:\d{2})Z$/, '$1') : value;
}

function formatDisplayDate(value) {
  if (!value) {
    return 'Latest Edition';
  }

  const parsed = new Date(sanitizeIso(value));
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(parsed);
}

function formatTimezone(tz) {
  if (!tz) return tz;
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date());
    return parts.find((p) => p.type === 'timeZoneName')?.value ?? tz;
  } catch {
    return tz.split('/').pop().replace(/_/g, ' ');
  }
}

function fidelityUrl(symbol) {
  return `https://digital.fidelity.com/prgw/digital/research/quote/dashboard/summary?symbol=${encodeURIComponent(symbol)}`;
}

function renderList(items, emptyMessage, renderItem) {
  if (!items.length) {
    return `<p class="empty-state">${escapeHtml(emptyMessage)}</p>`;
  }

  return `<div class="card-grid">${items.map(renderItem).join('')}</div>`;
}

function renderMetricCard(label, value, detail = '') {
  return `
    <article class="metric-card">
      <span class="metric-label">${escapeHtml(label)}</span>
      <strong class="metric-value font-mono">${escapeHtml(value)}</strong>
      ${detail ? `<span class="metric-detail">${escapeHtml(detail)}</span>` : ''}
    </article>
  `;
}

function renderHistoryRail(items = []) {
  if (!items.length) {
    return '';
  }

  return `
    <aside class="history-rail surface-card" aria-label="Report history">
      <div class="history-rail-header">
        <span class="section-label">Archive</span>
        <h2>Report History</h2>
      </div>
      <div class="history-scroll">
        ${items
          .map(
            (item) => `
              <a class="history-link${item.isActive ? ' is-active' : ''}" href="${escapeHtml(item.href || '#')}">
                <strong>${escapeHtml(item.label || item.date || 'Edition')}</strong>
                <span>${escapeHtml(item.date || '')}</span>
              </a>
            `,
          )
          .join('')}
      </div>
    </aside>
  `;
}

function renderWatchlistCard(watchlist) {
  return `
    <article class="surface-card watchlist-card hard-shadow-hover">
      <div class="card-topline">
        <div>
          <span class="card-kicker">Desk List</span>
          <h3>${escapeHtml(watchlist.name)}</h3>
        </div>
        <span class="pill pill-soft">${escapeHtml(watchlist.priority)}</span>
      </div>
      <p class="body-copy">${escapeHtml(watchlist.ruleSummary)}</p>
      <dl class="inline-metrics">
        <div><dt>Symbols</dt><dd>${escapeHtml(watchlist.symbols)}</dd></div>
        <div><dt>Universe</dt><dd>${escapeHtml(watchlist.id)}</dd></div>
      </dl>
    </article>
  `;
}

function renderSignalCard(signal) {
  const companyDisplay = signal.companyName && signal.companyName !== signal.symbol
    ? `<span>${escapeHtml(signal.companyName)}</span>`
    : '';
  return `
    <article class="surface-card signal-card hard-shadow-hover">
      <div class="card-topline">
        <div>
          <span class="card-kicker">Lead Signal</span>
          <h3><a href="#symbol/${encodeURIComponent(signal.symbol)}" class="symbol-detail-link">${escapeHtml(signal.symbol)}</a> ${companyDisplay}</h3>
          <div class="watchlist-tags">${(signal.watchlists ?? []).map(w => `<span class="pill pill-soft">${escapeHtml(w)}</span>`).join('')}</div>
        </div>
      </div>
      <dl class="signal-meta">
        <div><dt>Price</dt><dd>${escapeHtml(formatPrice(signal.lastPrice))}</dd></div>
        <div><dt>Change</dt><dd>${escapeHtml(formatPercent(signal.changePercent))}</dd></div>
        <div><dt>Status</dt><dd>${escapeHtml(signal.status)}</dd></div>
      </dl>
      <div class="rule-tags">
        ${(signal.ruleNames ?? []).filter(Boolean).map(name => `<span class="pill rule-tag">${escapeHtml(name)}</span>`).join('')}
      </div>
    </article>
  `;
}

function renderOptionCard(signal) {
  const topPickBadge = signal.highlighted
    ? `<span class="pill pill-alert options-top-pick">&#9733; Top Pick</span>`
    : '';
  const cardClass = signal.highlighted
    ? 'surface-card signal-card hard-shadow-hover options-highlight'
    : 'surface-card signal-card hard-shadow-hover';
  return `
    <article class="${cardClass}">
      <div class="card-topline">
        <div>
          <span class="card-kicker">Options Desk</span>${topPickBadge}
          <h3><a href="${fidelityUrl(signal.symbol)}" target="_blank" rel="noopener noreferrer">${escapeHtml(signal.symbol)}</a> <span>${escapeHtml(signal.strategy)}</span></h3>
          <p>Expires ${escapeHtml(signal.expiration)}</p>
        </div>
      </div>
      <p class="signal-reason">${escapeHtml(signal.reason)}</p>
    </article>
  `;
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
const TIMINGS = ['Before Open', 'After Close', 'TBD'];

function groupEarningsByWeek(earningsWatch) {
  const grid = {};
  for (const day of WEEKDAYS) {
    grid[day] = { 'Before Open': [], 'After Close': [], 'TBD': [] };
  }
  for (const entry of earningsWatch) {
    const day = entry.weekday;
    const timing = TIMINGS.includes(entry.timing) ? entry.timing : 'TBD';
    if (grid[day]) {
      grid[day][timing].push(entry);
    }
  }
  return grid;
}

function priorityClass(priority) {
  if (!priority) return '';
  const p = String(priority).toLowerCase();
  if (p.includes('very')) return 'ec-priority-very-high';
  if (p === 'high') return 'ec-priority-high';
  return '';
}

function renderEarningsCalendar(earningsWatch, reportDate) {
  if (!earningsWatch.length) {
    return '<p class="empty-state">No earnings events scheduled for this week.</p>';
  }

  const grid = groupEarningsByWeek(earningsWatch);

  let weekLabel = '';
  const firstDate = earningsWatch.find(e => e.date)?.date || reportDate;
  if (firstDate) {
    try {
      const d = new Date(firstDate + 'T12:00:00');
      const dayOfWeek = d.getDay();
      const diff = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
      const monday = new Date(d);
      monday.setDate(d.getDate() + diff);
      weekLabel = `Week of ${new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(monday)}`;
    } catch {
      weekLabel = '';
    }
  }

  const PRIMARY_TIMINGS = ['Before Open', 'After Close'];

  const dayCols = WEEKDAYS.map(day => {
    const slots = grid[day];
    const hasAny = TIMINGS.some(t => slots[t].length > 0);

    const renderTickerList = items => items.map(e => `
      <li class="ec-ticker-item ${priorityClass(e.priority)}">
        <a href="${fidelityUrl(e.symbol)}" target="_blank" rel="noopener noreferrer" class="ec-symbol">${escapeHtml(e.symbol)}</a>
        ${e.companyName && e.companyName !== e.symbol ? `<span class="ec-company">${escapeHtml(e.companyName)}</span>` : ''}
      </li>
    `).join('');

    const primarySlots = PRIMARY_TIMINGS.map(timing => {
      const items = slots[timing];
      return `
        <div class="ec-slot">
          <div class="ec-slot-label">${escapeHtml(timing)}</div>
          ${items.length
            ? `<ul class="ec-ticker-list">${renderTickerList(items)}</ul>`
            : '<span class="ec-slot-empty">—</span>'}
        </div>
      `;
    }).join('');

    const tbdItems = slots['TBD'] || [];
    const tbdHtml = tbdItems.length ? `
      <div class="ec-slot ec-slot-tbd">
        <div class="ec-slot-label">TBD</div>
        <ul class="ec-ticker-list">${renderTickerList(tbdItems)}</ul>
      </div>
    ` : '';

    return `
      <div class="ec-day-col${hasAny ? '' : ' ec-day-empty'}">
        <div class="ec-day-header">${escapeHtml(day)}</div>
        ${hasAny
          ? `<div class="ec-day-body">${primarySlots}</div>${tbdHtml}`
          : '<div class="ec-day-body"><span class="ec-none">—</span></div>'}
      </div>
    `;
  }).join('');

  return `
    ${weekLabel ? `<p class="ec-week-label">${escapeHtml(weekLabel)}</p>` : ''}
    <div class="ec-grid">${dayCols}</div>
  `;
}

function renderRuleCard(ruleSet) {
  return `
    <article class="surface-card rule-card hard-shadow-hover">
      <div class="card-topline">
        <div>
          <span class="card-kicker">Rulebook</span>
          <h3>${escapeHtml(ruleSet.name)}</h3>
          <p>${escapeHtml(ruleSet.universe)}</p>
        </div>
      </div>
      <p class="body-copy">${escapeHtml(ruleSet.description)}</p>
      <p class="rule-natural-language">${escapeHtml(ruleSet.naturalLanguage)}</p>
    </article>
  `;
}

function generateSignalBulletin(signal) {
  const pct = signal.changePercent;
  const price = formatPrice(signal.lastPrice);
  let momentum;
  if (pct >= 3) momentum = `surging ${formatPercent(pct)} with strong momentum`;
  else if (pct >= 1.5) momentum = `up ${formatPercent(pct)}, trending higher above key averages`;
  else if (pct >= 0.5) momentum = `gaining ${formatPercent(pct)}, holding above moving averages`;
  else if (pct >= 0) momentum = `steady above key moving averages`;
  else if (pct >= -1) momentum = `pulling back ${formatPercent(pct)} but maintaining uptrend`;
  else momentum = `dipping ${formatPercent(pct)}, holding technical support`;
  return `${signal.symbol}: ${momentum} — at ${price}`;
}

function renderBulletinsTicker(signals = []) {
  const highPriority = signals.filter((s) => s.status === 'high priority');
  if (!highPriority.length) {
    return '';
  }

  const items = highPriority
    .map(
      (signal) => `
        <span class="ticker-item">
          <span class="ticker-tag">${escapeHtml(signal.symbol)}</span>
          ${escapeHtml(generateSignalBulletin(signal))}
        </span>
      `,
    )
    .join('');

  return `
    <section class="news-ticker" aria-label="High priority signals">
      <div class="news-ticker-track">
        ${items}
        ${items}
      </div>
    </section>
  `;
}

function renderFrontPageHighlights(highlights = []) {
  if (!highlights.length) return '';
  return `
    <ul class="front-page-highlights">
      ${highlights.map((h) => `<li>${escapeHtml(h)}</li>`).join('')}
    </ul>
  `;
}

function parseReasonConditions(reason) {
  if (!reason) return [];
  return reason.split(';').map(s => s.trim()).filter(Boolean);
}

export function renderDetailAnalysis(analysis) {
  if (!analysis || typeof analysis !== 'object') return '';

  const summaryHtml = analysis.summary
    ? `<p class="ai-summary body-copy">${escapeHtml(analysis.summary)}</p>`
    : '';

  const rulesRows = (analysis.rules ?? []).map(r => {
    const statusIcon = r.status === 'warning' ? '⚠️' : '🚩';
    const statusLabel = r.status === 'warning' ? 'Monitoring' : 'Triggered';
    return `
      <tr>
        <td class="ai-table-priority">${escapeHtml(r.priority ?? 'High')}</td>
        <td class="ai-table-rule">${escapeHtml(r.name ?? '')}</td>
        <td class="ai-table-status">${escapeHtml(statusIcon)} ${escapeHtml(statusLabel)}</td>
        <td class="ai-table-details">${escapeHtml(r.details ?? '')}</td>
      </tr>
    `;
  }).join('');

  const targets = analysis.priceTargets ?? {};

  const resistanceHtml = (targets.resistance ?? []).map(r => `
    <div class="price-level">
      <span class="price-level-label">${escapeHtml(r.label ?? '')}</span>
      <span class="price-level-value font-mono">${escapeHtml(formatPrice(r.price))}</span>
      ${r.note ? `<span class="price-level-note">${escapeHtml(r.note)}</span>` : ''}
    </div>
  `).join('');

  const supportHtml = (targets.support ?? []).map(r => `
    <div class="price-level">
      <span class="price-level-label">${escapeHtml(r.label ?? '')}</span>
      <span class="price-level-value font-mono">${escapeHtml(formatPrice(r.price))}</span>
      ${r.note ? `<span class="price-level-note">${escapeHtml(r.note)}</span>` : ''}
    </div>
  `).join('');

  const entry = targets.entry;
  const stopLoss = targets.stopLoss;
  const entryHtml = entry ? `
    <div class="ai-price-col">
      <div class="ai-price-col-header">Entry / Exit</div>
      <div class="price-level">
        <span class="price-level-label">Ideal Entry</span>
        <span class="price-level-value font-mono">${escapeHtml(formatPrice(entry.low))} — ${escapeHtml(formatPrice(entry.high))}</span>
        ${entry.note ? `<span class="price-level-note">${escapeHtml(entry.note)}</span>` : ''}
      </div>
      ${stopLoss ? `
        <div class="price-level price-level-stop">
          <span class="price-level-label">Hard Stop-Loss</span>
          <span class="price-level-value font-mono is-negative">${escapeHtml(formatPrice(stopLoss.price))}</span>
          ${stopLoss.note ? `<span class="price-level-note">${escapeHtml(stopLoss.note)}</span>` : ''}
        </div>
      ` : ''}
    </div>
  ` : '';

  const verdict = analysis.verdict ?? {};
  const verdictHtml = (verdict.action || verdict.rationale || verdict.strategy) ? `
    <div class="ai-block ai-verdict">
      <div class="ai-verdict-header">
        <h3 class="ai-block-heading">Final Trading Verdict</h3>
        ${verdict.action ? `<span class="ai-verdict-action">${escapeHtml(verdict.action)}</span>` : ''}
      </div>
      ${verdict.rationale ? `<p class="body-copy">${escapeHtml(verdict.rationale)}</p>` : ''}
      ${verdict.strategy ? `<p class="body-copy ai-strategy">${escapeHtml(verdict.strategy)}</p>` : ''}
    </div>
  ` : '';

  return `
    <section class="ai-analysis-section">
      <div class="section-heading">
        <span class="section-label">AI Analysis</span>
        <h2>Trading Brief</h2>
      </div>

      ${summaryHtml}

      ${rulesRows ? `
        <div class="ai-block">
          <h3 class="ai-block-heading">Rule Scanning Status</h3>
          <div class="ai-table-wrapper">
            <table class="ai-rule-table">
              <thead>
                <tr>
                  <th>Priority</th><th>Rule</th><th>Status</th><th>Trigger Details</th>
                </tr>
              </thead>
              <tbody>${rulesRows}</tbody>
            </table>
          </div>
        </div>
      ` : ''}

      ${(resistanceHtml || supportHtml || entryHtml) ? `
        <div class="ai-block">
          <h3 class="ai-block-heading">Price Action Navigation</h3>
          <div class="ai-price-grid">
            ${resistanceHtml ? `
              <div class="ai-price-col">
                <div class="ai-price-col-header">Resistance</div>
                ${resistanceHtml}
              </div>
            ` : ''}
            ${supportHtml ? `
              <div class="ai-price-col">
                <div class="ai-price-col-header">Support</div>
                ${supportHtml}
              </div>
            ` : ''}
            ${entryHtml}
          </div>
        </div>
      ` : ''}

      ${verdictHtml}
    </section>
  `;
}

export function renderSymbolDetail(report, symbol) {
  const normalized = createEmptyReport(report);
  const allSignals = [...(normalized.stockSignals ?? []), ...(normalized.optionsSignals ?? [])];
  const signal = allSignals.find(s => s.symbol === symbol);

  if (!signal) {
    return `
      <div class="dashboard-shell">
        <main class="dashboard-main">
          <a class="back-link" href="#">&#8592; Back to Report</a>
          <p class="empty-state">No signal data found for <strong>${escapeHtml(symbol)}</strong>.</p>
        </main>
      </div>
    `;
  }

  const ruleSetsByName = Object.fromEntries(
    (normalized.ruleSets ?? []).map(rs => [rs.name, rs])
  );

  const ruleCards = (signal.ruleNames ?? []).filter(Boolean).map(name => {
    const rs = ruleSetsByName[name];
    return `
      <article class="surface-card rule-explanation-card">
        <div class="rule-explanation-header">
          <span class="card-kicker">Rule</span>
          <h3>${escapeHtml(name)}</h3>
        </div>
        ${rs ? `
          <p class="body-copy">${escapeHtml(rs.description)}</p>
          <p class="rule-natural-language">${escapeHtml(rs.naturalLanguage)}</p>
        ` : ''}
      </article>
    `;
  }).join('');

  const conditions = parseReasonConditions(signal.reason);
  const conditionsHtml = conditions.length ? `
    <div class="reason-conditions">
      <span class="section-label">Trigger values</span>
      <ul class="condition-list">
        ${conditions.map(c => `<li class="condition-item font-mono">${escapeHtml(c)}</li>`).join('')}
      </ul>
    </div>
  ` : '';

  const statusClass = signal.status === 'high priority' ? 'pill pill-alert' : 'pill pill-soft';
  const companyDisplay = signal.companyName && signal.companyName !== signal.symbol
    ? ` — ${signal.companyName}`
    : '';

  return `
    <div class="dashboard-shell">
      <main class="dashboard-main detail-main">
        <a class="back-link" href="#">&#8592; Back to Report</a>

        <header class="detail-masthead newsprint-texture">
          <div class="masthead-rule"></div>
          <div class="masthead-topline">
            <span class="section-label">Signal Detail</span>
            <span>${escapeHtml(formatDisplayDate(normalized.reportDate))}</span>
          </div>
          <div class="detail-hero">
            <div>
              <h1 class="detail-symbol">${escapeHtml(symbol)}</h1>
              ${companyDisplay ? `<p class="detail-company">${escapeHtml(companyDisplay.slice(3))}</p>` : ''}
            </div>
            <div class="detail-hero-meta">
              <div class="detail-price">${escapeHtml(formatPrice(signal.lastPrice))}</div>
              <div class="detail-change ${signal.changePercent >= 0 ? 'is-positive' : 'is-negative'}">${escapeHtml(formatPercent(signal.changePercent))}</div>
              <span class="${statusClass}">${escapeHtml(signal.status)}</span>
            </div>
          </div>
          <div class="detail-watchlists">
            ${(signal.watchlists ?? []).map(w => `<span class="pill pill-soft">${escapeHtml(w)}</span>`).join('')}
            <a href="${fidelityUrl(symbol)}" target="_blank" rel="noopener noreferrer" class="pill fidelity-link">Fidelity chart ↗</a>
          </div>
        </header>

        ${conditionsHtml}

        <section class="detail-rules-section">
          <div class="section-heading">
            <span class="section-label">Triggered Rules</span>
            <h2>Why this signal fired</h2>
            <p>${escapeHtml(signal.ruleNames?.length ?? 0)} rule${signal.ruleNames?.length !== 1 ? 's' : ''} matched for ${escapeHtml(symbol)} on this session.</p>
          </div>
          <div class="rule-explanation-grid">
            ${ruleCards || '<p class="empty-state">No rule details available.</p>'}
          </div>
        </section>

        <div id="ai-analysis-placeholder" class="ai-analysis-loading" aria-live="polite" aria-label="Loading trading brief">
          <div class="ai-analysis-section">
            <div class="section-heading">
              <span class="section-label">AI Analysis</span>
              <h2>Trading Brief</h2>
            </div>
            <p class="ai-loading-message">Generating trading brief…</p>
          </div>
        </div>

        <div class="ornament-divider" aria-hidden="true">✧ ✧ ✧</div>
      </main>
    </div>
  `;
}

export function renderReportApp(report) {
  const normalized = createEmptyReport(report);
  const validationErrors = validateReport(normalized);
  const editionDate = formatDisplayDate(normalized.reportDate);
  const generatedDate = formatDisplayDate(normalized.generatedAt || normalized.reportDate);
  const displayTitle = `${editionDate} Analysis Report`;
  const tzLabel = formatTimezone(normalized.timezone);
  const highPrioritySignals = normalized.stockSignals.filter((s) => s.status === 'high priority');

  return `
    <div class="dashboard-shell">
      <div class="dashboard-layout">
        ${renderHistoryRail(normalized.reportHistory)}

        <main class="dashboard-main">
          <header class="masthead newsprint-texture">
            <div class="masthead-rule"></div>
            <div class="masthead-topline">
              <span>Vol. 1</span>
              <span>${escapeHtml(editionDate)}</span>
              <span>${escapeHtml(tzLabel)} Edition</span>
            </div>
            <div class="masthead-title-row">
              <p class="masthead-kicker">Nightly market plan</p>
              <h1>${escapeHtml(displayTitle)}</h1>
              <p class="masthead-stamp">Printed for the next session</p>
            </div>
            <div class="masthead-bottomline">
              <span>Published ${escapeHtml(generatedDate)}</span>
              <span>${escapeHtml(normalized.universe.totalSymbols)} symbols under review</span>
              <span>${escapeHtml(normalized.universe.activeLists.length)} active desks</span>
            </div>
          </header>

          <nav class="quick-nav" aria-label="Report sections">
            <a href="#summary">Summary</a>
            <a href="#watchlists">Watchlists</a>
            <a href="#earnings-watch">Earnings</a>
            <a href="#stock-signals">Stocks</a>
            <a href="#options-signals">Options</a>
          </nav>

          ${renderBulletinsTicker(normalized.stockSignals)}

          ${validationErrors.length ? `<section class="surface-card warning-card"><strong>Report validation warning</strong><p>${escapeHtml(validationErrors.join('; '))}</p></section>` : ''}

          <section id="summary" class="report-section lead-section newsprint-texture" data-section="summary-metrics">
            <article class="lead-story lead-story-full">
              <span class="section-label">Front Page</span>
              <h2>Today Highlights</h2>
              ${normalized.newsSummary ? `<p class="hero-copy lead-copy">${escapeHtml(normalized.newsSummary)}</p>` : ''}
              ${renderFrontPageHighlights(normalized.highlights)}
              <p class="lead-note">
                ${escapeHtml(normalized.universe.name)} currently spans ${escapeHtml(normalized.universe.totalSymbols)} symbols
                across ${escapeHtml(normalized.universe.activeLists.length)} active watchlists.
              </p>
            </article>

            <div class="metric-grid">
              ${renderMetricCard('Symbols tracked', normalized.summary.totalSymbols)}
              ${renderMetricCard('Matched signals', normalized.summary.matchedSignals)}
              ${renderMetricCard('High priority', normalized.summary.highPrioritySignals)}
              ${renderMetricCard('Options candidates', normalized.summary.optionsCandidates)}
              ${renderMetricCard('Earnings watch', normalized.summary.earningsWatchCount)}
            </div>
          </section>

          <section id="watchlists" class="report-section">
            <div class="section-heading">
              <span class="section-label">Coverage Map</span>
              <h2>Watchlists</h2>
              <p>Independent list definitions with their own rule focus.</p>
            </div>
            ${renderList(normalized.watchlists, 'No watchlists configured.', renderWatchlistCard)}
          </section>

          <section id="earnings-watch" class="report-section" data-section="earnings-watch">
            <div class="section-heading">
              <span class="section-label">Calendar</span>
              <h2>Earnings Watch</h2>
              <p>Names that deserve faster follow-up around the earnings window.</p>
            </div>
            ${normalized.earningsChartUrl ? `
              <figure class="earnings-chart">
                <img src="${escapeHtml(normalized.earningsChartUrl)}" alt="Most anticipated earnings releases this week" loading="lazy">
                <figcaption>Source: Earnings Whispers — most anticipated releases for the week</figcaption>
              </figure>
            ` : ''}
            ${renderEarningsCalendar(normalized.earningsWatch, normalized.reportDate)}
          </section>

          <section id="stock-signals" class="report-section inverted-section" data-section="stock-signals">
            <div class="section-heading">
              <span class="section-label">Lead Tape</span>
              <h2>Top Stock Signals</h2>
              <p>High-priority names for tomorrow based on trend, momentum, and event context.</p>
            </div>
            ${renderList(highPrioritySignals, 'No high-priority stock signals matched this evening.', renderSignalCard)}
          </section>

          <section id="options-signals" class="report-section" data-section="options-signals">
            <div class="section-heading">
              <span class="section-label">Derivatives Desk</span>
              <h2>Top Options Ideas</h2>
              <p>Directional and premium-selling candidates for next-day planning.</p>
            </div>
            ${renderList(normalized.optionsSignals, 'No options ideas matched this evening.', renderOptionCard)}
          </section>

          <div class="ornament-divider" aria-hidden="true">✧ ✧ ✧</div>

          <footer class="report-footer">
            <span>Edition: Vol. 1.0</span>
            <span>Printed in ${escapeHtml(normalized.timezone)}</span>
            <span>${escapeHtml(normalized.universe.name)} Evening Desk</span>
          </footer>
        </main>
      </div>
    </div>
  `;
}
