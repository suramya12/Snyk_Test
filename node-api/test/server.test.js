const test = require('node:test');
const assert = require('node:assert/strict');
const https = require('node:https');
const selfsigned = require('selfsigned');

const app = require('../server');

async function request(pathname) {
  const pem = await selfsigned.generate(
    [{ name: 'commonName', value: 'localhost' }],
    { keySize: 2048 }
  );

  return new Promise((resolve, reject) => {
    const server = https.createServer({ key: pem.private, cert: pem.cert }, app).listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      const req = https.request({
        hostname: '127.0.0.1',
        port,
        path: pathname,
        method: 'GET',
        rejectUnauthorized: false
      }, (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          body += chunk;
        });
        res.on('end', () => {
          server.close();
          resolve({ statusCode: res.statusCode, body });
        });
      });
      req.on('error', (err) => {
        server.close();
        reject(err);
      });
      req.end();
    });
  });
}

test('search endpoint treats injected SQL-like input as data, not code', async () => {
  const response = await request('/search?q=%22%20OR%201%3D1%20--');
  assert.equal(response.statusCode, 200);
  assert.deepEqual(JSON.parse(response.body), []);
});

test('read endpoint rejects path traversal attempts', async () => {
  const response = await request('/read?file=../package.json');
  assert.equal(response.statusCode, 400);
  assert.match(response.body, /invalid path/i);
});

test('home endpoint escapes untrusted HTML in the message', async () => {
  const response = await request('/?msg=<script>alert(1)</script>');
  assert.equal(response.statusCode, 200);
  assert.match(response.body, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/i);
});
