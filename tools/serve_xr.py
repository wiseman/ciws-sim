# /// script
# requires-python = ">=3.11"
# ///
"""Serve the repo for testing on a headset, and take tools/xr-audio-test.html's answers.

Usage: uv run tools/serve_xr.py [port]   (default 8768; bound to 127.0.0.1, put behind `tailscale serve`)
A POST to /xr-audio-results appends its JSON body as a line to docs/vr/xr-audio-results.jsonl.
"""
import http.server
import json
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "docs" / "vr" / "xr-audio-results.jsonl"


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Always the latest: the headset reloads while the files change
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_POST(self):
        if self.path != "/xr-audio-results":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        report = json.loads(body)
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        with RESULTS.open("a") as f:
            f.write(json.dumps(report) + "\n")
        print("results:", json.dumps(report), flush=True)
        self.send_response(204)
        self.end_headers()


port = int(sys.argv[1]) if len(sys.argv) > 1 else 8768
http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT))).serve_forever()
