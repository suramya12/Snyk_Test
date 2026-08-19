const express = require('express');
const rateLimit = require('express-rate-limit');
const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');
const crypto = require('crypto');

const app = express();
app.disable('x-powered-by');
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.urlencoded({ extended: true }));
app.use(rateLimit({
  windowMs: 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: 'Too many requests'
}));

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const users = [
  { id: 1, name: 'alice' },
  { id: 2, name: 'bob' },
  { id: 3, name: 'charlie' }
];

const allowedViewFiles = {
  'index.ejs': path.join(__dirname, 'views', 'index.ejs')
};

app.get('/', (req, res) => {
  const userMsg = typeof req.query.msg === 'string' ? req.query.msg : '<em>Welcome!</em>';
  const msg = escapeHtml(userMsg);
  res.render('index', { msg });
});

app.get('/search', (req, res) => {
  const q = String(req.query.q || '').trim().toLowerCase();
  const rows = users
    .filter((user) => user.name.includes(q))
    .map(({ id, name }) => ({ id, name }));
  res.json(rows);
});

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

app.get('/ping', (req, res) => {
  const host = String(req.query.host || '127.0.0.1');
  const allowedHostPattern = /^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|[a-zA-Z0-9.-]+)$/;

  if (!allowedHostPattern.test(host)) {
    return res.status(400).send('Invalid host');
  }

  execFile('ping', ['-c', '1', host], (err, stdout, stderr) => {
    if (err) return res.status(500).send(stderr || err.message);
    res.type('text/plain').send(stdout);
  });
});

app.get('/hash', (req, res) => {
  const text = String(req.query.text || 'password');
  const digest = crypto.createHash('sha256').update(text).digest('hex');
  res.json({ sha256: digest });
});

const API_KEY = process.env.API_KEY;
app.get('/secret', (req, res) => {
  if (!API_KEY) {
    return res.status(500).json({ error: 'API key is not configured' });
  }

  return res.json({ apiKey: API_KEY });
});

if (require.main === module) {
  app.listen(3000, () => console.log('Node API listening on 3000'));
}

module.exports = app;
