from flask import Flask, request, jsonify
import sqlite3
import subprocess
import yaml

app = Flask(__name__)

# Basic in-memory DB
conn = sqlite3.connect(':memory:', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT, body TEXT)')
c.execute("INSERT INTO notes (title, body) VALUES ('hello','world'), ('todo','1. buy milk')")
conn.commit()

@app.route('/')
def index():
    x = request.args.get('x', '<i>hi</i>')
    # Jinja2 autoescape off for demo
    return f"<h1>Flask Demo</h1><div>{x}</div>"  # XSS sink

@app.route('/notes')
def notes():
    q = request.args.get('q', '')
    # SQL injection via string formatting
    sql = f"SELECT id,title FROM notes WHERE title LIKE '%{q}%'"
    rows = conn.execute(sql).fetchall()
    return jsonify(rows)

@app.route('/yaml', methods=['POST'])
def yaml_load():
    # Unsafe YAML load
    data = yaml.load(request.data, Loader=yaml.Loader)
    return jsonify(data)

@app.route('/ping')
def ping():
    target = request.args.get('target', '127.0.0.1')
    # Shell injection
    out = subprocess.check_output('ping -c 1 ' + target, shell=True)
    return out

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
