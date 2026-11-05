"""Tiny dashboard HTTP server bound to laptop localhost (not a public website).

Only public browser configuration is served. MQTT credentials remain in .env
and are never sent to /config.json.
"""

import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from shared.mqtt_connection import DEFAULT_HOST, project_id

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
DEFAULT_WS_URL = "wss://broker.hivemq.com:8884/mqtt"


def _positive_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def public_browser_config() -> dict:
    host = os.getenv("MQTT_HOST") or DEFAULT_HOST
    username = os.getenv("MQTT_USERNAME", "").strip()
    websocket_url = os.getenv("MQTT_WS_URL", "").strip()
    if not websocket_url and host == DEFAULT_HOST:
        websocket_url = DEFAULT_WS_URL

    return {
        "project_id": project_id(),
        "websocket_url": websocket_url,
        "automatic_connection": bool(websocket_url and not username),
        "stale_after_s": _positive_env("DASHBOARD_STALE_S", 20),
        "offline_after_s": _positive_env("DASHBOARD_OFFLINE_S", 60),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/config.json":
            payload = json.dumps(public_browser_config()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def log_message(self, format, *args):
        return


def start_dashboard_server(port: int | None = None):
    """Return server, background thread, and local URL.

    The caller owns shutdown/server_close. Binds to 127.0.0.1 by default.
    DASHBOARD_HOST=0.0.0.0 opens it to the local network for viewing on a phone;
    the page then has no login, so use it only on a trusted network.
    """
    requested_port = port if port is not None else int(os.getenv("DASHBOARD_PORT", "8000"))
    server = ThreadingHTTPServer((os.getenv("DASHBOARD_HOST", "127.0.0.1"), requested_port), DashboardHandler)
    thread = Thread(target=server.serve_forever, name="washalert-dashboard", daemon=True)
    thread.start()
    return server, thread, f"http://localhost:{server.server_port}"
