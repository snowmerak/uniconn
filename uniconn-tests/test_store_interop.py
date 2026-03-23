"""
Cross-language interop tests for IdentityStore.

Verifies that identity files saved by one language can be loaded by another.
Each test saves an identity in language A, then loads it in language B,
and compares the public key hex.
"""

import os
import subprocess
import sys
import tempfile

import pytest

# Paths.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GO_MOD = os.path.join(ROOT, "uniconn-go")
JS_DIR = os.path.join(ROOT, "uniconn-js", "node")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

PASSWORD = "interop-test-password"


def run_go_helper(cmd: str, path: str) -> str:
    """Run Go store helper, return stdout (hex pubkey)."""
    result = subprocess.run(
        ["go", "run", os.path.join(TESTS_DIR, "go_store_helper.go"), cmd, path, PASSWORD],
        capture_output=True, text=True, cwd=GO_MOD, timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"Go helper failed: {result.stderr}")
    return result.stdout.strip()


def run_node_helper(cmd: str, path: str) -> str:
    """Run Node.js store helper, return stdout (hex pubkey)."""
    result = subprocess.run(
        ["node", os.path.join(TESTS_DIR, "node_store_helper.mjs"), cmd, path, PASSWORD],
        capture_output=True, text=True, cwd=JS_DIR, timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"Node helper failed: {result.stderr}")
    return result.stdout.strip()


def run_python_save(path: str) -> str:
    """Save identity using Python, return hex pubkey."""
    sys.path.insert(0, os.path.join(ROOT, "uniconn-py"))
    from uniconn.secure.identity import Identity
    from uniconn.secure.store import save_identity

    identity = Identity.generate()
    save_identity(path, identity, PASSWORD.encode())
    return identity.public_key_bytes().hex()


def run_python_load(path: str) -> str:
    """Load identity using Python, return hex pubkey."""
    sys.path.insert(0, os.path.join(ROOT, "uniconn-py"))
    from uniconn.secure.store import load_identity

    identity = load_identity(path, PASSWORD.encode())
    return identity.public_key_bytes().hex()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestGoToPython:
    def test_go_save_python_load(self, tmp_dir):
        path = os.path.join(tmp_dir, "go.ucid")
        go_pubkey = run_go_helper("save", path)
        py_pubkey = run_python_load(path)
        assert go_pubkey == py_pubkey, f"Go→Python pubkey mismatch"


class TestPythonToGo:
    def test_python_save_go_load(self, tmp_dir):
        path = os.path.join(tmp_dir, "py.ucid")
        py_pubkey = run_python_save(path)
        go_pubkey = run_go_helper("load", path)
        assert py_pubkey == go_pubkey, f"Python→Go pubkey mismatch"


class TestGoToNode:
    def test_go_save_node_load(self, tmp_dir):
        path = os.path.join(tmp_dir, "go.ucid")
        go_pubkey = run_go_helper("save", path)
        node_pubkey = run_node_helper("load", path)
        assert go_pubkey == node_pubkey, f"Go→Node pubkey mismatch"


class TestNodeToGo:
    def test_node_save_go_load(self, tmp_dir):
        path = os.path.join(tmp_dir, "node.ucid")
        node_pubkey = run_node_helper("save", path)
        go_pubkey = run_go_helper("load", path)
        assert node_pubkey == go_pubkey, f"Node→Go pubkey mismatch"


class TestNodeToPython:
    def test_node_save_python_load(self, tmp_dir):
        path = os.path.join(tmp_dir, "node.ucid")
        node_pubkey = run_node_helper("save", path)
        py_pubkey = run_python_load(path)
        assert node_pubkey == py_pubkey, f"Node→Python pubkey mismatch"


class TestPythonToNode:
    def test_python_save_node_load(self, tmp_dir):
        path = os.path.join(tmp_dir, "py.ucid")
        py_pubkey = run_python_save(path)
        node_pubkey = run_node_helper("load", path)
        assert py_pubkey == node_pubkey, f"Python→Node pubkey mismatch"
