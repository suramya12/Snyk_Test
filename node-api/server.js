const express = require('express');
const path = require('path');
const fs = require('fs');
const { exec } = require('child_process');
const crypto = require('crypto');

const app = express();
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.urlencoded({ extended: true }));

const users = [
  { id: 1, name: 'alice', password: 'secret' },
  { id: 2, name: 'bob', password: 'hunter2' },
  { id: 3, name: 'charlie', password: 'p@ssw0rd' }
];

const allowedViewFiles = {
  'index.ejs': path.join(__dirname, 'views', 'index.ejs')
};

// Index with reflected XSS sink via unsafe EJS
app.get('/', (req, res) => {
  const msg = req.query.msg || '<em>Welcome!</em>';
  res.render('index', { msg }); // index.ejs uses unescaped output
});

// Search is now implemented without SQL string interpolation.
app.get('/search', (req, res) => {
  const q = String(req.query.q || '').trim().toLowerCase();
  const rows = users
    .filter((user) => user.name.includes(q))
    .map(({ id, name }) => ({ id, name }));
  res.json(rows);
});

// Path traversal is blocked by only allowing a small, explicit set of view files.
app.get('/read', (req, res) => {
  const requested = String(req.query.file || 'index.ejs');
  const resolved = allowedViewFiles[requested];

  if (!resolved) {
    return res.status(400).send('Invalid path');
  }

  try {
    const data = fs.readFileSync(resolved, 'utf8');
    res.type('text/plain').send(data);
  } catch (e) {
    res.status(404).send('Not found');
  }
});

// Command Injection
app.get('/ping', (req, res) => {
  const host = req.query.host || '127.0.0.1';
  exec('ping -c 1 ' + host, (err, stdout, stderr) => { // vulnerable
    if (err) return res.status(500).send(stderr);
    res.type('text/plain').send(stdout);
  });
});

// Weak crypto
app.get('/hash', (req, res) => {
  const text = req.query.text || 'password';
  const md5 = crypto.createHash('md5').update(text).digest('hex');
  res.json({ md5 });
});

// Hardcoded secret usage (for SAST pattern)
const API_KEY = 'sk_test_hardcoded_please_rotate';
app.get('/secret', (req, res) => res.json({ apiKey: API_KEY }));

if (require.main === module) {
  app.listen(3000, () => console.log('Node API listening on 3000'));
}

module.exports = app;
