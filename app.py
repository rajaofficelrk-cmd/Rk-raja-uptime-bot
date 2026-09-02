from flask import Flask, render_template, request, jsonify
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests

app = Flask(__name__)
DB = "uptime.db"
CHECK_INTERVAL = 60

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS monitors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        status TEXT DEFAULT 'unknown',
        last_code INTEGER,
        response_ms REAL DEFAULT 0,
        checks INTEGER DEFAULT 0,
        successes INTEGER DEFAULT 0,
        last_check TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS checks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        monitor_id INTEGER,
        ok INTEGER,
        response_ms REAL,
        status_code INTEGER,
        checked_at TEXT
    )""")
    c.commit()
    c.close()

def valid_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    return url if p.scheme in ("http", "https") and p.netloc else None

def do_check(monitor):
    start = time.perf_counter()
    ok = False
    code = None
    try:
        r = requests.get(
            monitor["url"], timeout=10, allow_redirects=True,
            headers={"User-Agent": "RK-Raja-Uptime-Monitor/1.0"}
        )
        code = r.status_code
        ok = 200 <= code < 400
    except requests.RequestException:
        pass

    ms = round((time.perf_counter() - start) * 1000, 1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    c = db()
    c.execute("""UPDATE monitors SET status=?, last_code=?, response_ms=?,
                 checks=checks+1, successes=successes+?, last_check=? WHERE id=?""",
              ("up" if ok else "down", code, ms, 1 if ok else 0, now, monitor["id"]))
    c.execute("""INSERT INTO checks(monitor_id,ok,response_ms,status_code,checked_at)
                 VALUES(?,?,?,?,?)""",
              (monitor["id"], 1 if ok else 0, ms, code, now))
    c.commit()
    c.close()

def monitor_loop():
    while True:
        c = db()
        monitors = c.execute("SELECT * FROM monitors").fetchall()
        c.close()
        for m in monitors:
            do_check(m)
        time.sleep(CHECK_INTERVAL)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/monitors")
def monitors():
    c = db()
    rows = [dict(x) for x in c.execute("SELECT * FROM monitors ORDER BY id DESC")]
    c.close()
    for x in rows:
        x["uptime"] = round((x["successes"] / x["checks"]) * 100, 2) if x["checks"] else 0
    return jsonify(rows)

@app.post("/api/monitors")
def add_monitor():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    url = valid_url(data.get("url"))
    if not name or not url:
        return jsonify({"error": "Name and valid URL are required"}), 400
    c = db()
    cur = c.execute("INSERT INTO monitors(name,url) VALUES(?,?)", (name,url))
    c.commit()
    monitor_id = cur.lastrowid
    row = c.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
    c.close()
    threading.Thread(target=do_check, args=(row,), daemon=True).start()
    return jsonify({"ok": True})

@app.post("/api/monitors/<int:mid>/check")
def check_one(mid):
    c = db()
    row = c.execute("SELECT * FROM monitors WHERE id=?", (mid,)).fetchone()
    c.close()
    if not row:
        return jsonify({"error":"Monitor not found"}), 404
    threading.Thread(target=do_check, args=(row,), daemon=True).start()
    return jsonify({"ok": True})

@app.delete("/api/monitors/<int:mid>")
def delete_monitor(mid):
    c = db()
    c.execute("DELETE FROM checks WHERE monitor_id=?", (mid,))
    c.execute("DELETE FROM monitors WHERE id=?", (mid,))
    c.commit()
    c.close()
    return jsonify({"ok": True})

@app.get("/api/summary")
def summary():
    c = db()
    rows = c.execute("SELECT * FROM monitors").fetchall()
    c.close()
    total = len(rows)
    up = sum(x["status"] == "up" for x in rows)
    down = sum(x["status"] == "down" for x in rows)
    paused = 0
    checks = sum(x["checks"] for x in rows)
    successes = sum(x["successes"] for x in rows)
    uptime = round(successes/checks*100, 2) if checks else 0
    responses = [x["response_ms"] for x in rows if x["response_ms"]]
    avg = round(sum(responses)/len(responses)) if responses else 0
    return jsonify({"total":total,"up":up,"down":down,"paused":paused,
                    "uptime":uptime,"avg":avg})

if __name__ == "__main__":
    init_db()
    threading.Thread(target=monitor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
