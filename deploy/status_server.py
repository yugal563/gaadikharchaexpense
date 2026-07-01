#!/usr/bin/env python3
"""Minimal HTTP server exposing pipeline job status from MySQL (for Cloudflare quick tunnel)."""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.db import get_connection

PORT = int(__import__("os").getenv("STATUS_PORT", "8765"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if path.startswith("/status/"):
            job_id = path.split("/status/", 1)[1].strip("/")
            if not job_id:
                self._json(400, {"error": "job_id required"})
                return
            try:
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT job_id, status, current_stage, category, expense_row_id, "
                        "error_message, original_url, preprocessed_url, "
                        "stage1_completed_at, stage6_completed_at, created_at "
                        "FROM stage_tracking WHERE job_id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                conn.close()
                if not row:
                    self._json(404, {"error": f"job {job_id} not found"})
                    return
                self._json(200, row)
            except Exception as e:
                self._json(500, {"error": str(e)})
            return
        self._json(404, {"error": "use GET /health or GET /status/{job_id}"})

    def _json(self, code, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[status] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Status server listening on http://0.0.0.0:{PORT}")
    server.serve_forever()
