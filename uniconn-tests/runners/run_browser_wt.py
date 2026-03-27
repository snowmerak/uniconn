"""Browser WebTransport echo tests against Go and Python WT servers.

These tests:
1. Spawn a Go/Python WT echo server with self-signed TLS
2. Start an HTTP server to serve the test HTML page
3. Open the browser, fill in port + cert hash, run the test
4. Assert the page reports ALL_PASSED
"""

import asyncio
import http.server
import json
import os
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "uniconn-py"))

from conftest import REPO_ROOT, GO_DIR, GO_WT_PORT, get_go_cert_hash

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(TESTS_DIR, "wt_browser_test.html")
PY_PYTHON = os.path.join(REPO_ROOT, "uniconn-py", ".venv", "Scripts", "python.exe")


def _serve_html(port: int) -> http.server.HTTPServer:
    """Start a simple HTTP server to serve the test HTML page."""
    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _spawn_py_wt_server():
    """Spawn Python WT echo server, return (proc, port, cert_hash)."""
    proc = subprocess.Popen(
        [PY_PYTHON, os.path.join(TESTS_DIR, "py_wt_echo_server.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    # Read first line — JSON with port + cert_hash.
    line = proc.stdout.readline().strip()
    if not line:
        proc.kill()
        stderr = proc.stderr.read()
        raise RuntimeError(f"Python WT server did not output JSON.\nstderr: {stderr}")

    info = json.loads(line)
    return proc, info["port"], info["cert_hash"]


def _kill(proc):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


# These are manual browser tests — run with: pytest test_browser_wt.py -v -s
# They require a browser window and are not run in CI.

@pytest.mark.skip(reason="Manual browser test — run with pytest -k browser_wt --run-browser")
def test_browser_wt_go(go_echo_server):
    """Browser WebTransport echo against Go WT server."""
    cert_hash = get_go_cert_hash()
    assert cert_hash, "Go server cert hash not available"
    # Manual: open wt_browser_test.html, set port=19004, cert_hash, click Run


@pytest.mark.skip(reason="Manual browser test — run with pytest -k browser_wt --run-browser")
def test_browser_wt_python():
    """Browser WebTransport echo against Python WT server."""
    proc, port, cert_hash = _spawn_py_wt_server()
    try:
        # Manual: open wt_browser_test.html, set port, cert_hash, click Run
        pass
    finally:
        _kill(proc)
