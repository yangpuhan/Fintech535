"""
Serve docs/ (the whole site, every assignment) locally and answer one
question the published site cannot.

    python covered_call/local_server.py
    # http://127.0.0.1:8765/data.html

Pages is what gets graded; this is a tool. The only thing it adds over
`python -m http.server` is /api/status, which reports whether LSEG Workspace
is actually reachable from this machine — so the Data page can say "live"
here and "Data connection required" on github.io, truthfully, without the
published build ever carrying a credential.
"""

from __future__ import annotations

import json
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
HOST, PORT = "127.0.0.1", 8765

# The desktop API the lseg-data library talks to. Workspace has to be running
# and signed in for any of these to accept a connection. It takes the first
# free port from 9000 up — on 8 Oct 2026 it came up on 9003, and a check of
# 9000 alone reported it shut while the pull was working.
WORKSPACE_PORTS = (*range(9000, 9011), 9060)


def workspace_status() -> dict:
    """
    Is Workspace listening? A TCP connect is enough and costs milliseconds.

    Opening a real lseg session here would be more truthful and would also
    hang this handler for several seconds when Workspace is down, which is
    exactly the case the page needs a fast answer for.
    """
    for port in WORKSPACE_PORTS:
        with socket.socket() as s:
            s.settimeout(0.35)
            if s.connect_ex((HOST, port)) == 0:
                return {"lseg": True, "session": f"desktop.workspace :{port}"}
    return {"lseg": False, "session": None,
            "detail": "nothing listening on 9000-9010 or 9060"}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib's spelling
        if self.path.split("?")[0] == "/api/status":
            body = json.dumps(workspace_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # the page may be opened from a file:// URL or another port
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        if "/api/status" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    if not (DOCS / "wheel.js").exists():
        raise SystemExit("docs/wheel.js is missing — run `python -m wheel.build` first")
    status = workspace_status()
    print(f"serving {DOCS}")
    print(f"  http://{HOST}:{PORT}/            the graded page")
    print(f"  http://{HOST}:{PORT}/data.html   provenance and connection state")
    print(f"  LSEG Workspace: {'reachable' if status['lseg'] else status['detail']}")
    ThreadingHTTPServer((HOST, PORT),
                        partial(Handler, directory=str(DOCS))).serve_forever()


if __name__ == "__main__":
    main()
