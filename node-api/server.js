const express = require('express');
const path = require('path');
const fs = require('fs');
const { exec } = require('child_process');
const crypto = require('crypto');
const sqlite3 = require('sqlite3').verbose();
const _ = require('lodash');

const app = express();
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.urlencoded({ extended: true }));

// In-memory DB for demo
const db = new sqlite3.Database(':memory:');
db.serialize(() => {
  db.run('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, password TEXT)');
  db.run("INSERT INTO users (name, password) VALUES ('alice','secret'), ('bob','hunter2'), ('charlie','p@ssw0rd')");
});

// Index with reflected XSS sink via unsafe EJS
app.get('/', (req, res) => {
  const msg = req.query.msg || '<em>Welcome!</em>';
  res.render('index', { msg }); // index.ejs uses unescaped output
});

// SQL Injection (string concat)
app.get('/search', (req, res) => {
  const q = req.query.q || '';
  const sql = `SELECT id, name FROM users WHERE name LIKE "%${q}%"`; // vulnerable
  db.all(sql, (err, rows) => {
    if (err) return res.status(500).send(err.message);
    res.json(rows);
  });
});

// Path Traversal
app.get('/read', (req, res) => {
  const f = req.query.file || 'views/index.ejs';
  try {
    // No validation or normalization
    const data = fs.readFileSync(path.join(__dirname, f), 'utf8');
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

app.listen(3000, () => console.log('Node API listening on 3000'));
