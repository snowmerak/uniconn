"""Assert Go/Python/Node P2P interoperability with bounded, owned subprocesses."""
from pathlib import Path
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]

class ManagedProcess:
    def __init__(self, name, command, cwd=ROOT):
        self.name = name
        self.events = queue.Queue()
        self.logs = []
        self.process = subprocess.Popen(
            [str(part) for part in command], cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.logs.append(line.rstrip())
            self.logs = self.logs[-50:]
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    self.events.put(event)
            except (ValueError, TypeError):
                pass

    def wait_event(self, kind, timeout=30, predicate=lambda event: True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                if event.get("event") == kind and predicate(event):
                    return event
            except queue.Empty:
                if self.process.poll() is not None and not self.reader.is_alive():
                    raise RuntimeError(f"{self.name} exited ({self.process.returncode}) before {kind}:\n" + "\n".join(self.logs))
        raise TimeoutError(f"{self.name} did not report {kind} within {timeout}s:\n" + "\n".join(self.logs))

    def send(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.stdout.close()


def assert_message(event, expected):
    if event.get("event") != "msg_received" or event.get("data") != expected:
        raise AssertionError(f"expected {expected!r}, got {event!r}")


def main():
    processes = []
    def start(name, command):
        process = ManagedProcess(name, command)
        processes.append(process)
        return process

    with tempfile.TemporaryDirectory(prefix="uniconn-cross-") as temporary:
        temporary = Path(temporary)
        suffix = ".exe" if os.name == "nt" else ""
        relay_exe = temporary / ("relay" + suffix)
        client_exe = temporary / ("go-client" + suffix)
        subprocess.run(["node", ROOT / "uniconn-js/scripts/build.mjs", "core", "node"], check=True, timeout=60)
        for source, output in [("relay.go", relay_exe), ("go_client.go", client_exe)]:
            subprocess.run(["go", "build", "-o", output, ROOT / "uniconn-tests/tools_go" / source],
                           cwd=ROOT / "uniconn-go", check=True, timeout=60)
        try:
            r1 = start("R1", [relay_exe, "-tcp=127.0.0.1:0", "-neg=127.0.0.1:0"])
            i1 = r1.wait_event("started")
            r2 = start("R2", [relay_exe, "-tcp=127.0.0.1:0", "-kcp=127.0.0.1:0", "-neg=127.0.0.1:0", f"-seeds={i1['negotiate']}"])
            i2 = r2.wait_event("started")
            r3 = start("R3", [relay_exe, "-tcp=127.0.0.1:0", "-neg=127.0.0.1:0", f"-seeds={i2['negotiate']}"])
            i3 = r3.wait_event("started")
            py = start("Python", [sys.executable, ROOT / "uniconn-tests/tools_py/py_client.py", "--relay", i3["tcp"], "--relay-fp", i3["fingerprint"], "--role", "responder", "--wait-ack"])
            py_info = py.wait_event("connected")
            go = start("Go", [client_exe, "--relay", i2["kcp"], "--relay-fp", i2["fingerprint"], "--proto", "kcp", "--role", "responder", "--wait-ack"])
            go_info = go.wait_event("connected")
            js = start("Node", ["node", ROOT / "uniconn-tests/tools_ts/p2p_client.mjs", "--relay", i1["tcp"], "--relay-fp", i1["fingerprint"]])
            js.wait_event("connected")
            for peer, info, response in [(py, py_info, "PONG_FROM_PY"), (go, go_info, "PONG_FROM_GO")]:
                js.send(info["fingerprint"])
                assert_message(peer.wait_event("msg_received"), "PING_FROM_TS")
                assert_message(js.wait_event("msg_received", predicate=lambda event: event.get("target_fingerprint") == info["fingerprint"]), response)
                if peer.process.wait(timeout=10) != 0:
                    raise RuntimeError(f"{peer.name} failed during receipt verification")
                print(f"PASS Node -> {peer.name}: authenticated mesh tunnel and exact echo")
            js.process.stdin.close()
            if js.process.wait(timeout=10) != 0:
                raise RuntimeError("Node client failed after data exchange")
        finally:
            for process in reversed(processes):
                process.close()


if __name__ == "__main__":
    main()
