export function createEmptyReport(overrides = {}) {
  return {
    reportLabel: 'Nightly Stock Analysis Report',
    reportDate: '',
    generatedAt: '',
    timezone: 'America/Los_Angeles',
    universe: {
      name: 'SPY 500',
      totalSymbols: 0,
      activeLists: [],
    },
    summary: {
      totalSymbols: 0,
      matchedSignals: 0,
      highPrioritySignals: 0,
      optionsCandidates: 0,
      earningsWatchCount: 0,
    },
    highlights: [],
    newsSummary: '',
    earningsChartUrl: '',
    reportHistory: [],
    watchlists: [],
    stockSignals: [],
    optionsSignals: [],
    earningsWatch: [],
    ruleSets: [],
    ...overrides,
  };
}

export function validateReport(report) {
  const errors = [];

  if (!report || typeof report !== 'object') {
    return ['report must be an object'];
  }

  if (typeof report.reportDate !== 'string' || report.reportDate.length === 0) {
    errors.push('reportDate must be a non-empty string');
  }

  if (typeof report.reportLabel !== 'string' || report.reportLabel.length === 0) {
    errors.push('reportLabel must be a non-empty string');
  }

  const arrayFields = ['reportHistory', 'watchlists', 'stockSignals', 'optionsSignals', 'earningsWatch', 'ruleSets'];
  for (const field of arrayFields) {
    if (!Array.isArray(report[field])) {
      errors.push(`${field} must be an array`);
    }
  }

  if (!report.summary || typeof report.summary !== 'object') {
    errors.push('summary must be an object');
  }

  if (!report.universe || typeof report.universe !== 'object') {
    errors.push('universe must be an object');
  }

  return errors;
}

