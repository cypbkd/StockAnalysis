import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = fileURLToPath(new URL('..', import.meta.url));
const preferredPort = Number(process.env.PORT || 4173);

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
