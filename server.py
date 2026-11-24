import errno
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import (
    build_ui_fragments,
    get_session,
    handle_get,
    handle_post,
)
from lexical_analyzer import analyze_code_lexically, validate_project_language

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
FIREBASE_CONFIG_PATH = ROOT / "firebase-applet-config.json"
SUPPORTED_LANGUAGES = {"Python", "C++", "Java", "JavaScript"}
IGNORED_SOCKET_WINERRORS = {10053, 10054}
IGNORED_SOCKET_ERRNOS = {
    errno.EPIPE,
    errno.ECONNRESET,
    errno.ECONNABORTED,
}


def is_client_disconnect(err):
    if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
        return True
    if isinstance(err, OSError):
        if getattr(err, "winerror", None) in IGNORED_SOCKET_WINERRORS:
            return True
        if getattr(err, "errno", None) in IGNORED_SOCKET_ERRNOS:
            return True
    return False


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


FREE_GEMINI_MODELS = ("gemini-4-hydrogen", "gemini-3.1-flash-lite")


def run_review(code, language):
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language ({language or 'unknown'}). This project only supports Python, C++, Java, and JavaScript."
        )
    return analyze_code_lexically(code, language)


def _call_gemini_model(model_name, api_key, system_prompt, user_prompt, schema):
    try:
        from google import genai
        from google.genai import types

        http_opts = {"headers": {"User-Agent": "aistudio-build"}}
        base_url = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
        if base_url:
            http_opts["base_url"] = base_url

        client = genai.Client(api_key=api_key, http_options=http_opts)
        resp = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return resp.text
    except ImportError:
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        base_url = (os.environ.get("GOOGLE_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com").rstrip("/")
        req = urllib.request.Request(
            f"{base_url}/v1beta/models/{model_name}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                "User-Agent": "aistudio-build",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return raw["candidates"][0]["content"]["parts"][0]["text"]


def generate_ai_improved_code(code, language, review=None):
    """Use free-tier Gemini models server-side to write a cleaner, bug-free version of the code."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing. Please configure it in Settings > Secrets.")

    target = language if language in SUPPORTED_LANGUAGES else "Python"
    bugs = (review or {}).get("bugs") or []
    improvements = (review or {}).get("improvements") or []

    findings_lines = []
    for b in bugs:
        findings_lines.append(f"- Bug (line {b.get('line', '?')}): {b.get('title', '')} — {b.get('description', '')}")
    for imp in improvements:
        findings_lines.append(f"- Improvement ({imp.get('category', 'Quality')}): {imp.get('title', '')} — {imp.get('description', '')}")
    findings_context = "\n".join(findings_lines) if findings_lines else "None reported; improve clarity, safety, and idiomatic style."

    system_prompt = (
        f"You are an expert senior {target} engineer. Rewrite the user's code into a clean, "
        f"production-ready, bug-free, idiomatic {target} version.\n"
        "Fix all flagged bugs and edge cases while preserving the intended public behavior and API.\n"
        "Return ONLY JSON matching the schema with improved_code_lines containing each line of the "
        "complete rewritten code (preserving leading indentation, with no markdown fences or line numbers)."
    )
    user_prompt = (
        f"Language: {target}\n\n"
        f"Lexical Findings to Address:\n{findings_context}\n\n"
        f"Original Code:\n{code}"
    )
    schema = {
        "type": "OBJECT",
        "properties": {
            "improved_code_lines": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Complete rewritten code split into an array of lines preserving indentation.",
            }
        },
        "required": ["improved_code_lines"],
    }

    last_err = None
    text = None
    for model_name in FREE_GEMINI_MODELS:
        try:
            text = _call_gemini_model(model_name, api_key, system_prompt, user_prompt, schema)
            break
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="ignore")
            if err.code == 403 or "API_KEY_INVALID" in err_body or "PERMISSION_DENIED" in err_body:
                raise ValueError("The configured GEMINI_API_KEY was rejected. Please verify it in Settings > Secrets.")
            if err.code in (404, 429) or "RESOURCE_EXHAUSTED" in err_body or "NOT_FOUND" in err_body:
                last_err = ValueError("Free-tier rate limit reached for Gemini API. Please wait a moment and try again.")
                continue
            raise ValueError(err_body or str(err))
        except Exception as err:
            msg = str(err)
            if "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg or "403" in msg:
                raise ValueError("The configured GEMINI_API_KEY was rejected. Please verify it in Settings > Secrets.")
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg or "NOT_FOUND" in msg or "404" in msg:
                last_err = ValueError("Free-tier rate limit reached for Gemini API. Please wait a moment and try again.")
                continue
            raise

    if text is None:
        raise last_err or ValueError("Gemini free-tier request failed. Please try again.")

    parsed = json.loads(text or "{}")
    lines = parsed.get("improved_code_lines") or []
    if not lines:
        raise ValueError("Gemini did not return an improved code rewrite. Please try again.")
    return "\n".join(str(line) for line in lines)


class ReviewHandler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except Exception as err:
            if not is_client_disconnect(err):
                raise

    def finish(self):
        try:
            super().finish()
        except Exception as err:
            if not is_client_disconnect(err):
                raise

    def send_bytes(self, status, content_type, data, send_body=True):
        try:
            self.send_response(status)
            if content_type:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            if send_body and data:
                self.wfile.write(data)
        except Exception as err:
            if not is_client_disconnect(err):
                raise

    def send_json(self, status, data):
        self.send_bytes(status, "application/json; charset=utf-8", json.dumps(data).encode("utf-8"))

    def do_HEAD(self):
        self.send_bytes(200, "text/html; charset=utf-8", b"", send_body=False)

    def do_GET(self):
        path = self.path.split("?", 1)[0].lstrip("/")
        if path == "favicon.ico":
            return self.send_bytes(204, None, b"", send_body=False)

        if path == "firebase-config.json":
            if FIREBASE_CONFIG_PATH.is_file():
                return self.send_bytes(200, "application/json; charset=utf-8", FIREBASE_CONFIG_PATH.read_bytes())
            return self.send_json(404, {"error": "Firebase config not found."})

        if path and path != "index.html":
            target = (PUBLIC_DIR / path).resolve()
            if target.is_relative_to(PUBLIC_DIR.resolve()) and target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                return self.send_bytes(200, f"{mime or 'application/octet-stream'}; charset=utf-8", target.read_bytes())

        self.send_bytes(200, "text/html; charset=utf-8", handle_get().encode("utf-8"))

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json(400, {"error": "Invalid Content-Length header."})

        if length < 0 or length > 2_097_152:
            return self.send_json(413, {"error": "Payload too large."})

        try:
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        except Exception as err:
            if is_client_disconnect(err):
                return
            return self.send_json(400, {"error": "Could not read request body."})

        if route == "/":
            parsed = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
            form = {k: v[-1] for k, v in parsed.items()}
            html = handle_post(form, run_review, ai_improve_fn=generate_ai_improved_code)
            return self.send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

        if route == "/api/analyze-files":
            try:
                body = json.loads(raw_body or "{}")
                incoming = body.get("files") or []
                if not isinstance(incoming, list) or not incoming:
                    return self.send_json(400, {"error": "Please select at least one file to load."})
                if len(incoming) > 20:
                    return self.send_json(400, {"error": "Please upload up to 20 files at a time."})

                auto_review = bool(body.get("auto_review", False))
                session_id, session = get_session(body.get("session_id"))
                existing = list(session.get("attached_files") or []) if body.get("append", True) else []
                first_new_index = None

                for raw_file in incoming:
                    if not isinstance(raw_file, dict):
                        continue
                    name = str(raw_file.get("name") or "untitled.py").strip() or "untitled.py"
                    source = "drive" if raw_file.get("source") == "drive" else "local"
                    code = str(raw_file.get("code") or "")
                    if not code.strip():
                        continue
                    lang = validate_project_language(code, raw_file.get("language"), filename=name)

                    if auto_review:
                        review, complexity = run_review(code, lang)
                    else:
                        review, complexity = None, None

                    entry = {
                        "name": name,
                        "source": source,
                        "language": lang,
                        "code": code,
                        "review": review,
                        "complexity": complexity,
                    }

                    replaced = False
                    for idx, prev in enumerate(existing):
                        if prev.get("name") == name and prev.get("source") == source:
                            existing[idx] = entry
                            if first_new_index is None:
                                first_new_index = idx
                            replaced = True
                            break
                    if not replaced:
                        if first_new_index is None:
                            first_new_index = len(existing)
                        existing.append(entry)

                if not existing or first_new_index is None:
                    return self.send_json(400, {"error": "Selected files were empty or contained no readable code."})

                active_idx = first_new_index
                active_file = existing[active_idx]
                session["attached_files"] = existing
                session["active_file_index"] = active_idx
                session["review"] = active_file["review"]
                session["complexity"] = active_file["complexity"]
                session["error"] = None

                state = {
                    "language": active_file["language"],
                    "code": active_file["code"],
                    "active_tab": "bugs",
                    "expanded_bug": 0,
                    "highlighted_line": None,
                }
                return self.send_json(200, build_ui_fragments(state, session_id, session))
            except ValueError as err:
                return self.send_json(400, {"error": str(err)})
            except Exception as err:
                return self.send_json(500, {"error": str(err) or "Failed to load files."})

        if route != "/api/review":
            return self.send_json(404, {"error": "Not found"})

        try:
            body = json.loads(raw_body or "{}")
            code = str(body.get("code") or "")
            if not code.strip():
                return self.send_json(400, {"error": "Please paste some code first."})
            review, complexity = run_review(code, body.get("language"))
            return self.send_json(200, {"review": review, "complexity": complexity})
        except ValueError as err:
            return self.send_json(400, {"error": str(err)})
        except Exception as err:
            return self.send_json(500, {"error": str(err) or "Something went wrong during review."})

    def log_message(self, format, *args):
        pass


class QuietHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        except Exception as err:
            if not is_client_disconnect(err):
                raise

    def handle_error(self, request, client_address):
        _, err, _ = sys.exc_info()
        if err is not None and is_client_disconnect(err):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("PORT", "3000"))
    server = QuietHTTPServer(("0.0.0.0", port), ReviewHandler)
    print(f"AI Code Reviewer server running on http://localhost:{port}")
    server.serve_forever()
