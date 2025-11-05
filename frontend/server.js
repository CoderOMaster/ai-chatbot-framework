const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = process.env.PORT || 3000;

function fileExists(p) {
  try {
    return fs.existsSync(p);
  } catch (e) {
    return false;
  }
}

const standalonePath = path.join(__dirname, '.next', 'standalone', 'server.js');

if (fileExists(standalonePath)) {
  // If Next.js produced a standalone server, delegate to it
  const child = spawn(process.execPath, [standalonePath], {
    stdio: 'inherit',
    env: process.env,
  });
  child.on('exit', (code) => process.exit(code));
} else {
  // Minimal static server + health endpoint for environments without SSR
  const publicDir = path.join(__dirname, 'public');
  const nextStatic = path.join(__dirname, '.next', 'static');

  const server = http.createServer((req, res) => {
    const url = req.url.split('?')[0];

    if (url === '/' || url === '/index.html') {
      const indexPath = path.join(publicDir, 'index.html');
      if (fileExists(indexPath)) {
        const stream = fs.createReadStream(indexPath);
        res.writeHead(200, { 'Content-Type': 'text/html' });
        stream.pipe(res);
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('Next.js app (build not found)');
      return;
    }

    if (url === '/_health' || url === '/health' ) {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('OK');
      return;
    }

    // Serve files from public
    const publicFile = path.join(publicDir, url);
    if (fileExists(publicFile) && fs.statSync(publicFile).isFile()) {
      const stream = fs.createReadStream(publicFile);
      const ext = path.extname(publicFile).toLowerCase();
      const mime = ext === '.js' ? 'application/javascript' : ext === '.css' ? 'text/css' : 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': mime });
      stream.pipe(res);
      return;
    }

    // Serve next static assets if present
    if (url.startsWith('/_next/static') && fileExists(path.join(nextStatic, url.replace('/_next/static/', '')))) {
      const staticFile = path.join(__dirname, url);
      if (fileExists(staticFile) && fs.statSync(staticFile).isFile()) {
        const stream = fs.createReadStream(staticFile);
        res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
        stream.pipe(res);
        return;
      }
    }

    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
  });

  server.listen(PORT, () => {
    console.log(`Frontend static server listening on port ${PORT}`);
  });
}