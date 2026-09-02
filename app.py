import os
import sqlite3
import threading
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template

# =========================================================
# APP CONFIG
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "uptime.db")

app = Flask(__name__)

# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'DOWN',
            response_time REAL DEFAULT 0,
            last_checked TEXT,
            uptime REAL DEFAULT 100
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# MONITORING
# =========================================================

def check_url(url):
    start = time.time()

    try:
        response = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "RK-RAJA-Uptime-Monitor/1.0"
            }
        )

        response_time = round((time.time() - start) * 1000, 2)

        if 200 <= response.status_code < 400:
            return "UP", response_time

        return "DOWN", response_time

    except requests.RequestException:
        return "DOWN", 0


def monitor_loop():
    while True:
        try:
            conn = get_db()
            monitors = conn.execute(
                "SELECT * FROM monitors"
            ).fetchall()

            for monitor in monitors:
                status, response_time = check_url(monitor["url"])

                now = datetime.utcnow().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                conn.execute("""
                    UPDATE monitors
                    SET status = ?,
                        response_time = ?,
                        last_checked = ?
                    WHERE id = ?
                """, (
                    status,
                    response_time,
                    now,
                    monitor["id"]
                ))

            conn.commit()
            conn.close()

        except Exception as e:
            print("Monitor error:", e)

        time.sleep(60)


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/monitors")
def api_monitors():
    conn = get_db()

    monitors = conn.execute(
        "SELECT * FROM monitors ORDER BY id DESC"
    ).fetchall()

    data = [dict(row) for row in monitors]

    conn.close()

    return jsonify(data)


@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "service": "RK RAJA Uptime Bot",
        "time": datetime.utcnow().isoformat()
    })


# =========================================================
# STARTUP
# =========================================================

init_db()

monitor_thread = threading.Thread(
    target=monitor_loop,
    daemon=True
)

monitor_thread.start()


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
