import json
import mimetypes
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import handle_get, handle_post
from lexical_analyzer import analyze_code_lexically

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
SUPPORTED_LANGUAGES = {"JavaScript", "Python", "C++", "Java"}


def load_env():
    """Load key=value pairs from .env if present."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        return
    except ImportError:
        pass
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def run_review(code, language):
    target = language if language in SUPPORTED_LANGUAGES else "Python"
    return analyze_code_lexically(code, target)


class ReviewHandler(BaseHTTPRequestHandler):
    def send_bytes(self, status, content_type, data, send_body=True):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if send_body:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_json(self, status, data):
        self.send_bytes(status, "application/json; charset=utf-8", json.dumps(data).encode("utf-8"))

    def do_HEAD(self):
        self.send_bytes(200, "text/html; charset=utf-8", b"", send_body=False)

    def do_GET(self):
        path = self.path.split("?", 1)[0].lstrip("/")
        if path and path != "index.html":
            target = (PUBLIC_DIR / path).resolve()
            if target.is_relative_to(PUBLIC_DIR.resolve()) and target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                return self.send_bytes(200, f"{mime or 'application/octet-stream'}; charset=utf-8", target.read_bytes())

        self.send_bytes(200, "text/html; charset=utf-8", handle_get().encode("utf-8"))

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_048_576:
            return self.send_json(413, {"error": "Payload too large."})

        raw_body = self.rfile.read(length).decode("utf-8")

        if route == "/":
            parsed = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
            form = {k: v[-1] for k, v in parsed.items()}
            html = handle_post(form, run_review)
            return self.send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

        if route != "/api/review":
            return self.send_json(404, {"error": "Not found"})

        try:
            body = json.loads(raw_body or "{}")
            code = str(body.get("code") or "")
            if not code.strip():
                return self.send_json(400, {"error": "Please paste some code first."})
            review, complexity = run_review(code, body.get("language"))
            return self.send_json(200, {"review": review, "complexity": complexity})
        except Exception as err:
            return self.send_json(500, {"error": str(err) or "Something went wrong during review."})

    def log_message(self, format, *args):
        pass


class QuietHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        _, err, _ = sys.exc_info()
        if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("PORT", "3000"))
    server = QuietHTTPServer(("0.0.0.0", port), ReviewHandler)
    print(f"AI Code Reviewer server running on http://0.0.0.0:{port}")
    server.serve_forever()
