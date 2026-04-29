import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = fileURLToPath(new URL('..', import.meta.url));
const preferredPort = Number(process.env.PORT || 4173);

// Sample analysis response returned by the mock /api/analysis endpoint.
// Mirrors the AMD fixture data so the detail page renders fully in local dev.
const MOCK_ANALYSIS = {
  summary: "This ticker is exhibiting strong momentum with multiple technical rules firing simultaneously. The price action shows institutional conviction on elevated volume.",
  rules: [
    { name: "ATH Breakout", priority: "High", status: "triggered", details: "Price at or above 52-week high on volume ratio >= 1.5x" },
    { name: "High-Volume Momentum Day", priority: "High", status: "triggered", details: "Volume ratio >= 2x average; RSI >= 55 confirming direction" },
    { name: "Strong Trending Day", priority: "High", status: "triggered", details: "Daily change >= 3% with close above EMA-20" },
  ],
  priceTargets: {
    resistance: [
      { label: "R1 (Pivot)", price: 365.0, note: "First pivot resistance — near-term ceiling" },
      { label: "R2 (Extended)", price: 385.0, note: "Next major target on continuation" },
    ],
    support: [
      { label: "S1 (Pivot)", price: 318.5, note: "Key retest zone" },
      { label: "EMA-20", price: 298.4, note: "Short-term trend anchor" },
      { label: "SMA-50", price: 270.2, note: "Medium-term floor" },
    ],
    entry: { low: 318.0, high: 330.0, note: "Wait for a pullback to S1 before adding" },
    stopLoss: { price: 290.0, note: "Below EMA-20 — invalidates the breakout" },
  },
  verdict: {
    action: "Hold / Tactical Buy on Pullback",
    rationale: "ATH Breakout, High-Volume Day, and Strong Trending Day in confluence signal institutional accumulation.",
    strategy: "Do not chase. Wait for pullback to $318-$330 S1 zone. Hard stop below $290.",
  },
  fundamentals: {
    pe: 42.3,
    forwardPe: 31.8,
    eps: 8.22,
    forwardEps: 10.94,
    earningsGrowth: 25.4,
    // 8.22 × (8.5 + 2×25.4) × 4.4/4.7 = 8.22 × 59.3 × 0.9362 ≈ 456.28
    fairPrice: 456.28,
    bondYield: 4.7,
  },
};

const contentTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

async function serveFile(res, filePath) {
  const type = contentTypes[extname(filePath)] || 'application/octet-stream';
  const body = await readFile(filePath);
  res.writeHead(200, { 'Content-Type': type });
  res.end(body);
}

const fixtureRoutes = {
  '/reports/latest/report.json': join(rootDir, 'tests/fixture-report.json'),
};

const server = createServer(async (req, res) => {
  try {
    const urlPath = req.url === '/' ? '/index.html' : decodeURIComponent(req.url.split('?')[0]);
    const safePath = normalize(urlPath).replace(/^(\.\.[/\\])+/, '');

    // Serve mock config.json pointing to local analysis endpoint
    if (safePath === '/config.json') {
      const port = server.address()?.port ?? preferredPort;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ analysisUrl: `http://localhost:${port}/api/analysis` }));
      return;
    }

    // Mock on-demand analysis endpoint — returns sample data after a short delay
    if (safePath === '/api/analysis') {
      await new Promise(r => setTimeout(r, 600));
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify(MOCK_ANALYSIS));
      return;
    }

    if (fixtureRoutes[safePath]) {
      await serveFile(res, fixtureRoutes[safePath]);
      return;
    }

    await serveFile(res, join(rootDir, safePath));
  } catch {
    try {
      await serveFile(res, join(rootDir, 'index.html'));
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
    }
  }
});

function listenOnAvailablePort(port) {
  return new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off('error', onError);

      if (error.code === 'EADDRINUSE' && port < preferredPort + 10) {
        resolve(listenOnAvailablePort(port + 1));
        return;
      }

      reject(error);
    };

    server.once('error', onError);
    server.listen(port, () => {
      server.off('error', onError);
      resolve(port);
    });
  });
}

try {
  const port = await listenOnAvailablePort(preferredPort);
  process.stdout.write(`Static report server running at http://localhost:${port}\n`);
} catch (error) {
  process.stderr.write(`Unable to start static report server: ${error.message}\n`);
  process.exitCode = 1;
}
