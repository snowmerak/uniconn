import sys

import pytest

from run_p2p_cross import ManagedProcess, assert_message


def test_missing_or_wrong_echo_is_a_failure():
    with pytest.raises(AssertionError):
        assert_message({}, "PONG_FROM_PY")
    with pytest.raises(AssertionError):
        assert_message({"event": "msg_received", "data": "wrong"}, "PONG_FROM_PY")
    assert_message({"event": "msg_received", "data": "PONG_FROM_PY"}, "PONG_FROM_PY")


def test_early_process_exit_fails_readiness():
    process = ManagedProcess("early exit", [sys.executable, "-c", "raise SystemExit(2)"])
    try:
        with pytest.raises(RuntimeError, match="exited"):
            process.wait_event("started", timeout=1)
    finally:
        process.close()


def test_readiness_timeout_is_bounded():
    process = ManagedProcess("silent", [sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        with pytest.raises(TimeoutError):
            process.wait_event("started", timeout=0.05)
    finally:
        process.close()
