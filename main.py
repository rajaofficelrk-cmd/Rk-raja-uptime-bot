import os
import time
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# जिन websites को monitor करना है
WEBSITES = [
    {
        "name": "Google",
        "url": "https://www.google.com",
    },
    {
        "name": "GitHub",
        "url": "https://github.com",
    },
]

CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "60"))
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "15"))

status_data = {}
status_lock = threading.Lock()


HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rk Raja Uptime Bot</title>
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #111827, #1e3a8a);
            color: white;
            padding: 25px;
        }

        .container {
            width: 100%;
            max-width: 950px;
            margin: auto;
        }

        h1 {
            text-align: center;
            margin-bottom: 8px;
        }

        .subtitle {
            text-align: center;
            color: #cbd5e1;
            margin-bottom: 28px;
        }

        .card {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.25);
        }

        .top {
            display: flex;
            justify-content: space-between;
            gap: 15px;
            align-items: center;
        }

        .name {
            font-size: 22px;
            font-weight: bold;
        }

        .url {
            color: #bfdbfe;
            word-break: break-all;
            margin-top: 8px;
        }

        .status {
            padding: 9px 15px;
            border-radius: 30px;
            font-weight: bold;
            white-space: nowrap;
        }

        .up {
            background: #16a34a;
        }

        .down {
            background: #dc2626;
        }

        .unknown {
            background: #64748b;
        }

        .details {
            color: #e2e8f0;
            margin-top: 15px;
            line-height: 1.7;
        }

        .refresh {
            display: block;
            width: 180px;
            margin: 22px auto;
            padding: 12px;
            border: 0;
            border-radius: 8px;
            background: #38bdf8;
            color: #082f49;
            font-weight: bold;
            cursor: pointer;
            font-size: 15px;
        }

        .refresh:hover {
            background: #7dd3fc;
        }

        .footer {
            text-align: center;
            color: #cbd5e1;
            margin-top: 25px;
            font-size: 14px;
        }

        @media (max-width: 600px) {
            body {
                padding: 15px;
            }

            .top {
                align-items: flex-start;
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Rk Raja Uptime Bot</h1>
        <div class="subtitle">Website monitoring dashboard</div>

        {% for item in websites %}
        <div class="card">
            <div class="top">
                <div>
                    <div class="name">{{ item.name }}</div>
                    <div class="url">{{ item.url }}</div>
                </div>

                <div class="status {{ item.status_class }}">
                    {{ item.status }}
                </div>
            </div>

            <div class="details">
                HTTP Status: {{ item.http_status }}<br>
                Response Time: {{ item.response_time }}<br>
                Last Checked: {{ item.last_checked }}<br>
                Message: {{ item.message }}
            </div>
        </div>
        {% else %}
        <div class="card">
            No websites configured.
        </div>
        {% endfor %}

        <button class="refresh" onclick="location.reload()">
            Refresh Status
        </button>

        <div class="footer">
            Auto check interval: {{ interval }} seconds
        </div>
    </div>
</body>
</html>
"""


def valid_url(url):
    """Check URL format."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def check_website(website):
    """Check one website and return safe status data."""
    name = website.get("name", "Unknown")
    url = website.get("url", "")

    result = {
        "name": name,
        "url": url,
        "status": "DOWN",
        "status_class": "down",
        "http_status": "-",
        "response_time": "-",
        "last_checked": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        ),
        "message": "",
    }

    if not valid_url(url):
        result["message"] = "Invalid URL"
        return result

    try:
        start_time = time.perf_counter()

        response = requests.get(
            url,
            timeout=TIMEOUT,
            headers={
                "User-Agent": "Rk-Raja-Uptime-Bot/1.0"
            },
            allow_redirects=True,
        )

        elapsed = time.perf_counter() - start_time

        result["http_status"] = response.status_code
        result["response_time"] = f"{elapsed:.2f} seconds"

        if 200 <= response.status_code < 400:
            result["status"] = "UP"
            result["status_class"] = "up"
            result["message"] = "Website is working"
        else:
            result["status"] = "DOWN"
            result["status_class"] = "down"
            result["message"] = f"HTTP error {response.status_code}"

    except requests.exceptions.Timeout:
        result["message"] = "Request timeout"

    except requests.exceptions.ConnectionError:
        result["message"] = "Connection failed"

    except requests.exceptions.RequestException as error:
        result["message"] = str(error)

    except Exception as error:
        result["message"] = f"Unexpected error: {error}"

    return result


def check_all_websites():
    """Check all configured websites."""
    new_data = {}

    for website in WEBSITES:
        url = website.get("url", "")
        new_data[url] = check_website(website)

    with status_lock:
        status_data.clear()
        status_data.update(new_data)


def background_checker():
    """Run website checks repeatedly in background."""
    while True:
        try:
            check_all_websites()
        except Exception as error:
            print("Background checker error:", error, flush=True)

        time.sleep(CHECK_INTERVAL)


@app.route("/")
def home():
    try:
        with status_lock:
            websites = list(status_data.values())

        return render_template_string(
            HTML_PAGE,
            websites=websites,
            interval=CHECK_INTERVAL,
        )

    except Exception as error:
        app.logger.exception("Home page error")
        return jsonify({
            "error": "Internal Server Error",
            "details": str(error),
        }), 500


@app.route("/api/status")
def api_status():
    with status_lock:
        return jsonify({
            "success": True,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "websites": list(status_data.values()),
        })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "message": "Rk Raja Uptime Bot is running",
    })


@app.route("/check")
def manual_check():
    check_all_websites()

    with status_lock:
        return jsonify({
            "success": True,
            "websites": list(status_data.values()),
        })


@app.errorhandler(404)
def page_not_found(error):
    return jsonify({
        "error": "Page not found",
        "available_routes": ["/", "/api/status", "/health", "/check"],
    }), 404


@app.errorhandler(500)
def internal_server_error(error):
    app.logger.exception("Internal server error")
    return jsonify({
        "error": "Internal Server Error",
        "message": "Application me error aa gaya. Render logs check karein.",
    }), 500


# Gunicorn is file se app object read karega
application = app


if __name__ == "__main__":
    check_all_websites()

    checker_thread = threading.Thread(
        target=background_checker,
        daemon=True,
    )
    checker_thread.start()

    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
