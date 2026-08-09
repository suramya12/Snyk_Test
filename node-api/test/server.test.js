const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const app = require('../server');

function request(pathname) {
  return new Promise((resolve, reject) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      const req = http.request({
        hostname: '127.0.0.1',
        port,
        path: pathname,
        method: 'GET'
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

test('search endpoint treats injected SQL as data, not code', async () => {
  const response = await request('/search?q=%22%20OR%201%3D1%20--');
  assert.equal(response.statusCode, 200);
  assert.deepEqual(JSON.parse(response.body), []);
});

test('read endpoint rejects path traversal attempts', async () => {
  const response = await request('/read?file=../package.json');
  assert.equal(response.statusCode, 400);
  assert.match(response.body, /invalid path/i);
});
