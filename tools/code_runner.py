"""Interactive Python Sandbox Code Runner for aZoth-local.

Mirrors and enhances Grok's Python code interpreter:
- Executes Python scripts inside the sandbox workspace (sandbox/workspace/)
- Captures stdout, stderr, execution time, and any generated files
- Enforces strict timeout controls to prevent runaway loops
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .workspace import WORKSPACE_DIR


def run_python(code: str, timeout_sec: int = 20) -> dict[str, Any]:
    """Execute Python code in the sandbox workspace environment and return results.
    
    Args:
        code: Complete Python script to execute.
        timeout_sec: Maximum execution time in seconds (default 20).
    """
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save code to a temporary script file in the workspace
    script_path = WORKSPACE_DIR / f"_temp_runner_{int(time.time()*1000)}.py"
    try:
        script_path.write_text(code, encoding="utf-8")

        start_time = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        elapsed = round(time.perf_counter() - start_time, 3)

        stdout = proc.stdout
        stderr = proc.stderr
        ok = proc.returncode == 0

        # Clean output
        output_display = stdout
        if stderr:
            if output_display:
                output_display += "\n\n[STDERR]:\n" + stderr
            else:
                output_display = stderr

        return {
            "ok": ok,
            "returncode": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout": stdout,
            "stderr": stderr,
            "output": output_display,
            "summary": f"Python executed in {elapsed}s (exit {proc.returncode})" if ok else f"Python failed with code {proc.returncode} in {elapsed}s",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Execution timed out after {timeout_sec} seconds.",
            "elapsed_seconds": timeout_sec,
            "summary": f"Timeout expired ({timeout_sec}s)",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "summary": f"Execution error: {e}",
        }
    finally:
        # Clean up temp script
        try:
            if script_path.exists():
                script_path.unlink()
        except Exception:
            pass
