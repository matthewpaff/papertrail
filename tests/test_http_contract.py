import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def request(url: str, body: bytes | None = None, origin: str | None = None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.read(2_000_000), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(2_000_000), dict(error.headers)


def check_http(name: str):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix=f"{name}-smoke-") as directory:
        log_path = Path(directory) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "server.py", "--port", str(port), "--db", str(Path(directory) / "demo.sqlite3")],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 15
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"{name}: server exited: {log_path.read_text(encoding='utf-8')}")
                    try:
                        status, data, _ = request(base + "/api/health")
                        assert status == 200, (name, status, data)
                        json.loads(data)
                        break
                    except (OSError, urllib.error.URLError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"{name}: startup timed out")
                        time.sleep(0.1)
                status, data, _ = request(base + "/")
                assert status == 200 and b"<html" in data.lower(), (name, "HTML", status)
                status, _, _ = request(base + "/nonexistent-path")
                assert status == 404, (name, "missing route", status)
                endpoint = {"rentwise": "/api/evaluate", "papertrail": "/api/ask", "runtrace": "/api/simulate"}[name]
                for malformed in (b"[]", b"null", b"{bad json", b'"text"'):
                    status, data, _ = request(base + endpoint, malformed)
                    assert status == 400, (name, "invalid JSON contract", status, data)
                    assert isinstance(json.loads(data).get("error"), str), (name, data)
                status, _, _ = request(base + endpoint, b"{}", "https://unrelated.example")
                assert status == 403, (name, "cross-site mutation", status)
                if name == "rentwise":
                    status, data, _ = request(base + endpoint, b'{"budget":"2200.00","months":12}')
                    result = json.loads(data)
                    assert status == 200 and result["results"], (name, status, result)
                    status, _, _ = request(base + "/api/book", b'{"listing":"sample-missing","key":"smoke-test-key","consent":true}')
                    assert status == 400, (name, "invalid booking", status)
                elif name == "papertrail":
                    status, data, _ = request(base + endpoint, b'{"query":"launch accessibility review"}')
                    result = json.loads(data)
                    assert status == 200 and result["sources"], (name, status, result)
                    status, data, _ = request(base + endpoint, b'{"query":"field equipment inventory"}')
                    assert status == 200 and json.loads(data)["abstained"], (name, "workspace isolation", status, data)
                else:
                    status, data, _ = request(base + endpoint, b'{"scenario":"baseline"}')
                    result = json.loads(data)
                    assert status == 201 and result["summary"]["status"] == "pass", (name, status, result)
                    status, data, _ = request(base + endpoint, b'{"scenario":"duplicate"}')
                    result = json.loads(data)
                    assert status == 201 and result["summary"]["status"] == "review", (name, status, result)
                return {"health": "passed", "dashboard": "passed", "missing_route": "passed", "malformed_json": "passed", "cross_site_denial": "passed", "vertical_slice": "passed"}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


class HTTPContractTests(unittest.TestCase):
    def test_local_http_vertical_slice(self):
        check_http('papertrail')
