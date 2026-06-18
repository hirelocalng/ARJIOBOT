"""Tiny local HTTP server for the FastAPI-compatible API app."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

logger.info("ArjioBot API starting up...")
try:
    from arjiobot.main import create_app

    app = create_app()
    from arjiobot.backtesting.research_profiles import get_strategy_profiles

    logger.info("ArjioBot API app created successfully (%d strategy profiles loaded)", len(get_strategy_profiles()))
except Exception:
    logger.exception("ArjioBot API failed to start during create_app()")
    raise


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(200, {"ok": True})

    def do_GET(self) -> None:
        try:
            if self.path in ("/", "/docs"):
                self._send_html(200, _docs_html())
                return
            status, payload = app.handle("GET", self.path)
            self._send(status, payload)
        except Exception:
            self._send_unhandled_error("GET")

    def do_DELETE(self) -> None:
        try:
            status, payload = app.handle("DELETE", self.path)
            self._send(status, payload)
        except Exception:
            self._send_unhandled_error("DELETE")

    def do_POST(self) -> None:
        try:
            if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                status, payload = app.handle("POST", self.path, files=self._read_multipart_files())
            else:
                status, payload = app.handle("POST", self.path, json_body=self._read_json())
            self._send(status, payload)
        except Exception:
            self._send_unhandled_error("POST")

    def do_PATCH(self) -> None:
        try:
            status, payload = app.handle("PATCH", self.path, json_body=self._read_json())
            self._send(status, payload)
        except Exception:
            self._send_unhandled_error("PATCH")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return None
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else None

    def _read_multipart_files(self):
        content_type = self.headers.get("Content-Type", "")
        boundary_match = re.search(r"boundary=([^;]+)", content_type)
        if not boundary_match:
            return None
        boundary = boundary_match.group(1).strip('"').encode("utf-8")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        marker = b"--" + boundary
        files = {}
        form = {}
        for part in body.split(marker):
            part = part.strip(b"\r\n")
            if not part or part == b"--" or b"\r\n\r\n" not in part:
                continue
            raw_headers, data = part.split(b"\r\n\r\n", 1)
            data = data.removesuffix(b"\r\n").removesuffix(b"--")
            headers = raw_headers.decode("utf-8", errors="replace")
            name_match = re.search(r'name="([^"]+)"', headers)
            filename_match = re.search(r'filename="([^"]*)"', headers)
            if not name_match:
                continue
            if not filename_match:
                form[name_match.group(1)] = data.decode("utf-8", errors="replace")
                continue
            content_type_match = re.search(r"Content-Type:\s*([^\r\n]+)", headers, re.IGNORECASE)
            files[name_match.group(1)] = (
                filename_match.group(1),
                data,
                content_type_match.group(1).strip() if content_type_match else "application/octet-stream",
            )
        if form:
            files["__form"] = form
        return files

    def _send_unhandled_error(self, method: str) -> None:
        logger.exception("Unhandled API error for %s %s", method, self.path)
        self._send(
            500,
            {
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Backend encountered an unexpected error. Check the server log for details.",
                },
            },
        )


def main() -> None:
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    logger.info("ArjioBot API listening on http://%s:%s", host, port)
    try:
        ThreadingHTTPServer((host, port), Handler).serve_forever()
    except Exception:
        logger.exception("ArjioBot API server crashed")
        raise


def _docs_html() -> str:
    paths = app.openapi()["paths"]
    rows = "\n".join(
        f"<tr><td><code>{path}</code></td><td>{', '.join(method.upper() for method in methods)}</td></tr>"
        for path, methods in sorted(paths.items())
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ArjioBot API Docs</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }}
    th {{ background: #eaf2f8; }}
    code {{ color: #0f766e; }}
  </style>
</head>
<body>
  <h1>ArjioBot API Docs</h1>
  <p>Local compatibility docs. OpenAPI JSON is available at <a href="/openapi.json">/openapi.json</a>.</p>
  <table>
    <thead><tr><th>Path</th><th>Methods</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""


if __name__ == "__main__":
    main()
