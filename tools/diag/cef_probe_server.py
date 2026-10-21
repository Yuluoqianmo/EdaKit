"""Isolated Capture browser capability probe (stdlib only, no production writes)."""
import argparse
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

WEB = Path(__file__).with_name("cef_probe_web")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "edakit-cef-probe")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    log_file = args.output / "events.jsonl"
    lock = threading.Lock()

    def record(event):
        event["utc"] = datetime.now(timezone.utc).isoformat()
        with lock, log_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            record({"kind": "http", "path": self.path[:2048], "status": status,
                    "bytes": len(body), "ua": self.headers.get("User-Agent", "")})

        def do_GET(self):
            path = urlsplit(self.path).path
            resources = {"/": ("index.html", "text/html; charset=utf-8"),
                         "/probe.js": ("probe.js", "application/javascript; charset=utf-8"),
                         "/probe.css": ("probe.css", "text/css; charset=utf-8"),
                         "/sample.svg": ("sample.svg", "image/svg+xml")}
            if path in resources:
                name, mime = resources[path]
                self.send(200, (WEB / name).read_bytes(), mime)
            elif path == "/ping":
                self.send(200, b'{"ok":true}', "application/json")
            elif path == "/reports":
                self.send(200, log_file.read_bytes() if log_file.exists() else b"", "application/x-ndjson; charset=utf-8")
            elif path == "/favicon.ico":
                self.send(204, b"", "image/x-icon")
            else:
                self.send(404, b"Not found", "text/plain")

        def do_POST(self):
            if urlsplit(self.path).path != "/report":
                self.send(404, b"Not found", "text/plain")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError("invalid report size")
                report = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(report, dict):
                    raise ValueError("report must be an object")
            except (ValueError, UnicodeError):
                self.send(400, b"Invalid report", "text/plain")
                return
            record({"kind": "browser", "report": report})
            self.send(200, b'{"saved":true}', "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    url_file = args.output / "url.txt"
    url = "http://127.0.0.1:%s/" % server.server_port
    url_file.write_text(url, encoding="ascii")
    record({"kind": "start", "url": url, "pid": os.getpid()})
    print("CEF probe: " + url, flush=True)
    print("URL file: " + str(url_file), flush=True)
    print("Report: " + str(log_file), flush=True)
    print("Keep this window open; Ctrl+C stops the probe.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if url_file.exists() and url_file.read_text(encoding="ascii") == url:
            url_file.unlink()
        record({"kind": "stop", "url": url})


if __name__ == "__main__":
    main()
