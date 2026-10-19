"""Local server for the welcome page: the "get to know you" form and the guide.

    python -m jobscan.onboard      (start.sh / start.command / start.bat run this)

Listens on 127.0.0.1 only, so nothing on the network can reach it. Saving the
form writes me/about-me.json and your CV into the me/ folder - nothing is
uploaded anywhere. Claude Code reads those files when you run /setup.
"""
from __future__ import annotations

import base64
import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "onboarding" / "index.html"
ME = ROOT / "me"
PORT = 8765
MAX_CV_BYTES = 10 * 1024 * 1024
CV_TYPES = {".pdf", ".docx", ".txt", ".md"}
MAX_BODY = 15 * 1024 * 1024   # a 10 MB CV is ~13.4 MB once base64-encoded
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


def _state() -> dict:
    return {
        "about": (ME / "about-me.json").exists(),
        "cv": any(ME.glob("cv.*")),
        "profile": (ME / "profile.md").exists(),
        "master": (ME / "master.json").exists(),
        "config": (ROOT / "config.yaml").exists(),
        "dashboard": (ROOT / "dashboard.html").exists(),
        "saved": json.loads((ME / "about-me.json").read_text()) if (ME / "about-me.json").exists() else None,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _host_ok(self) -> bool:
        # Only answer requests addressed to this machine by name. A web page
        # elsewhere could point its own domain at 127.0.0.1 ("DNS rebinding")
        # and read /api/state; its requests would carry that domain as Host.
        if self.headers.get("Host", "") in ALLOWED_HOSTS:
            return True
        self._send(403, b"Forbidden", "text/plain")
        return False

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        if self.path in ("/", "/index.html") or self.path.startswith("/#"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(200, _state())
        elif self.path == "/dashboard" and (ROOT / "dashboard.html").exists():
            self._send(200, (ROOT / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        if self.path != "/api/save":
            return self._send(404, b"Not found", "text/plain")
        # A page on another site cannot post here: browsers send an Origin
        # header, and only this page's own origin is accepted.
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._json(403, {"ok": False, "error": "Wrong origin."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self._json(413, {"ok": False, "error": "That file is too large. Export a smaller PDF (under 10 MB)."})
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"ok": False, "error": "That didn't arrive as valid data."})
        ME.mkdir(exist_ok=True)
        about = {k: v for k, v in (data.get("about") or {}).items() if isinstance(v, (str, list, bool))}
        cv = data.get("cv") or {}
        if cv.get("name") and cv.get("data"):
            ext = Path(cv["name"]).suffix.lower()
            if ext not in CV_TYPES:
                return self._json(400, {"ok": False, "error": "Your CV needs to be a PDF, Word (.docx) or text file."})
            raw = base64.b64decode(re.sub(r"^data:[^,]*,", "", cv["data"]))
            if len(raw) > MAX_CV_BYTES:
                return self._json(400, {"ok": False, "error": "That file is over 10 MB. Export a smaller PDF."})
            for old in ME.glob("cv.*"):
                old.unlink()
            (ME / f"cv{ext}").write_bytes(raw)
            about["cv_file"] = f"me/cv{ext}"
        else:
            existing = sorted(ME.glob("cv.*"))
            about["cv_file"] = f"me/{existing[0].name}" if existing else None
        (ME / "about-me.json").write_text(json.dumps(about, indent=2, ensure_ascii=False))
        self._json(200, {"ok": True, "state": _state()})

    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"jobscan is open at {url}  (press Ctrl+C here to stop it)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
