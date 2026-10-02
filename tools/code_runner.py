"""Interactive Python Sandbox Code Runner for aZoth-local.

Mirrors and enhances Grok's Python code interpreter:
- Executes Python scripts inside the sandbox workspace (sandbox/workspace/)
- Supports persistent stateful REPL sessions with session_id support
- Evaluates trailing expressions (Jupyter / IPython style)
- Automatically intercepts and saves matplotlib figures/plots as artifacts
- Strips ANSI escape sequences from tracebacks and output streams
- Enforces strict timeout controls with automatic process recovery
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .workspace import WORKSPACE_DIR

ROOT = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = Path(__file__).resolve().parent / "_repl_worker.py"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.is_file() and os.access(VENV_PYTHON, os.X_OK) else sys.executable

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal and traceback text."""
    if not text:
        return ""
    return ANSI_ESCAPE_RE.sub("", text)


class REPLSession:
    """Represents a stateful or ephemeral Python REPL session backed by a worker process."""

    def __init__(self, session_id: str, is_ephemeral: bool = False):
        self.session_id = session_id
        self.is_ephemeral = is_ephemeral
        self.proc: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.last_active = time.time()
        self._closed = False

    def _ensure_worker(self) -> subprocess.Popen[str]:
        """Ensure the worker process is running, launching a new one if necessary."""
        if self._closed:
            raise RuntimeError(f"REPL session '{self.session_id}' has been closed.")

        if self.proc is not None and self.proc.poll() is None:
            return self.proc

        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["MPLBACKEND"] = "Agg"
        env["PYTHON_COLORS"] = "0"
        env["NO_COLOR"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["AZOTH_WORKSPACE_DIR"] = str(WORKSPACE_DIR.resolve())

        # Include repo root and sandbox workspace in PYTHONPATH
        python_paths = [str(ROOT), str(WORKSPACE_DIR.resolve())]
        if "PYTHONPATH" in env:
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)

        cmd = [
            PYTHON_EXE,
            "-u",
            str(WORKER_SCRIPT),
        ]

        self.proc = subprocess.Popen(
            cmd,
            cwd=str(WORKSPACE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        return self.proc

    def execute(self, code: str, timeout_sec: int = 20) -> dict[str, Any]:
        """Execute Python code in this session and return the execution results."""
        if timeout_sec <= 0:
            timeout_sec = 20

        with self.lock:
            self.last_active = time.time()
            proc = self._ensure_worker()

            req = {
                "action": "execute",
                "code": code,
                "session_id": self.session_id,
            }

            try:
                if proc.stdin is None or proc.stdout is None:
                    raise RuntimeError("Worker process standard streams are not available.")

                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                # Worker died before write; restart once
                self._terminate_proc()
                proc = self._ensure_worker()
                if proc.stdin is None or proc.stdout is None:
                    return {
                        "ok": False,
                        "error": "Failed to communicate with REPL worker.",
                        "summary": "REPL worker startup failed",
                    }
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()

            # Read response asynchronously via queue with timeout
            resp_queue: queue.Queue[str | None] = queue.Queue()

            def _reader() -> None:
                try:
                    while True:
                        if proc.stdout is None:
                            break
                        line = proc.stdout.readline()
                        if not line:
                            break
                        if line.startswith("__AZOTH_REPL_RESULT__:"):
                            resp_queue.put(line[len("__AZOTH_REPL_RESULT__:"):].strip())
                            return
                except Exception:
                    pass
                resp_queue.put(None)

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()

            try:
                raw_json = resp_queue.get(timeout=timeout_sec)
            except queue.Empty:
                # Timeout occurred; terminate worker to cancel stuck execution
                self._terminate_proc()
                return {
                    "ok": False,
                    "error": f"Execution timed out after {timeout_sec} seconds.",
                    "elapsed_seconds": timeout_sec,
                    "summary": f"Timeout expired ({timeout_sec}s)",
                }

            if raw_json is None:
                # Subprocess exited or died without returning the result sentinel
                stderr_text = ""
                returncode = 1
                if proc.stderr:
                    try:
                        stderr_text = strip_ansi(proc.stderr.read())
                    except Exception:
                        pass
                if proc.poll() is not None:
                    returncode = proc.returncode

                self._terminate_proc()
                return {
                    "ok": False,
                    "returncode": returncode,
                    "error": f"REPL worker exited unexpectedly with code {returncode}.",
                    "stderr": stderr_text,
                    "output": stderr_text or f"Worker process terminated (code {returncode}).",
                    "summary": f"Python failed with code {returncode}",
                }

            try:
                res = json.loads(raw_json)
                if not isinstance(res, dict):
                    res = {"ok": True, "output": str(res)}
                return res
            except json.JSONDecodeError as err:
                return {
                    "ok": False,
                    "error": f"Failed to parse worker response: {err}",
                    "raw_response": raw_json,
                    "summary": "Invalid worker response",
                }

    def reset(self) -> bool:
        """Reset the execution state of this session."""
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                try:
                    if self.proc.stdin:
                        self.proc.stdin.write(json.dumps({"action": "reset"}) + "\n")
                        self.proc.stdin.flush()
                    if self.proc.stdout:
                        while True:
                            line = self.proc.stdout.readline()
                            if not line or line.startswith("__AZOTH_REPL_RESULT__:"):
                                break
                    return True
                except Exception:
                    self._terminate_proc()
                    return True
            return True

    def _terminate_proc(self) -> None:
        """Forcefully terminate the worker subprocess."""
        if self.proc is not None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None

    def close(self) -> None:
        """Close the session and terminate its worker process."""
        with self.lock:
            self._closed = True
            self._terminate_proc()


class SessionManager:
    """Manages active persistent REPL sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, REPLSession] = {}
        self._lock = threading.Lock()

    def get_session(self, session_id: str) -> REPLSession:
        """Get or create a persistent REPL session by ID."""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = REPLSession(session_id=session_id)
            return self._sessions[session_id]

    def reset_session(self, session_id: str) -> bool:
        """Reset the namespace of an active session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                return session.reset()
            return False

    def close_session(self, session_id: str) -> bool:
        """Close and remove an active session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                session.close()
                return True
            return False

    def close_all_sessions(self) -> None:
        """Terminate and clean up all active REPL sessions."""
        with self._lock:
            for session in list(self._sessions.values()):
                session.close()
            self._sessions.clear()

    def list_sessions(self) -> list[str]:
        """List active session IDs."""
        with self._lock:
            return list(self._sessions.keys())


# Global session manager instance
_SESSION_MANAGER = SessionManager()
atexit.register(_SESSION_MANAGER.close_all_sessions)


def get_session(session_id: str) -> REPLSession:
    """Retrieve an active persistent session by ID."""
    return _SESSION_MANAGER.get_session(session_id)


def reset_session(session_id: str) -> bool:
    """Reset the execution state of a persistent session."""
    return _SESSION_MANAGER.reset_session(session_id)


def close_session(session_id: str) -> bool:
    """Close and terminate a persistent session."""
    return _SESSION_MANAGER.close_session(session_id)


def close_all_sessions() -> None:
    """Close all active persistent sessions."""
    _SESSION_MANAGER.close_all_sessions()


def list_sessions() -> list[str]:
    """List all currently active persistent session IDs."""
    return _SESSION_MANAGER.list_sessions()


def run_python(
    code: str,
    timeout_sec: int = 20,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Execute Python code in the sandbox workspace environment and return results.

    Args:
        code: Complete Python script or interactive snippet to execute.
        timeout_sec: Maximum execution time in seconds (default 20).
        session_id: Optional ID for persistent stateful execution across calls.
                    If None, runs in an isolated ephemeral session.
    """
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    if session_id:
        session = _SESSION_MANAGER.get_session(session_id)
        return session.execute(code=code, timeout_sec=timeout_sec)
    else:
        # Isolated ephemeral session
        ephemeral_id = f"_ephem_{int(time.time()*1000)}_{threading.get_ident()}"
        session = REPLSession(session_id=ephemeral_id, is_ephemeral=True)
        try:
            return session.execute(code=code, timeout_sec=timeout_sec)
        finally:
            session.close()
