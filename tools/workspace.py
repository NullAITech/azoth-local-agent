"""Sandboxed Workspace & Safe Shell Execution for a-bot.

Provides isolated file operations and shell commands scoped inside
azoth-local-agent/sandbox/workspace/ with security guardrails.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = ROOT / "sandbox"
WORKSPACE_DIR = SANDBOX_DIR / "workspace"

WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Patterns that are blocked for safety
DANGEROUS_COMMANDS = [
    r"rm\s+-rf\s+[/~]",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
    r">/dev/sd[a-z]",
]


def resolve_safe_path(input_path: str, allow_parent: bool = False) -> Path:
    """Resolve path relative to sandbox workspace."""
    p = Path(input_path)
    if not p.is_absolute():
        p = (WORKSPACE_DIR / p).resolve()
    else:
        p = p.resolve()

    if not allow_parent and not str(p).startswith(str(WORKSPACE_DIR.resolve())):
        raise PermissionError(f"Path '{input_path}' is outside the sandbox workspace.")
    return p


def is_dangerous(command: str) -> bool:
    """Check if command matches dangerous patterns."""
    for pattern in DANGEROUS_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def run_shell(command: str, cwd: Optional[str] = None, timeout: int = 60) -> dict[str, Any]:
    """Execute a shell command inside the sandbox workspace."""
    if is_dangerous(command):
        return {
            "ok": False,
            "error": "Command blocked: contains dangerous system-level operations.",
            "command": command,
        }

    target_cwd = resolve_safe_path(cwd) if cwd else WORKSPACE_DIR
    target_cwd.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(target_cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env={**os.environ, "CWD": str(target_cwd)},
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[:15000],
            "stderr": proc.stderr[:5000],
            "returncode": proc.returncode,
            "command": command,
            "cwd": str(target_cwd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Command timed out after {timeout} seconds.",
            "command": command,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command}


def read_file(path: str, max_bytes: int = 200_000) -> dict[str, Any]:
    """Read a text file from the sandbox workspace."""
    try:
        resolved = resolve_safe_path(path)
        if not resolved.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if resolved.is_dir():
            return {"ok": False, "error": f"Path is a directory: {path}"}

        content = resolved.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            content = content[:max_bytes] + "\n... [truncated]"
        return {"ok": True, "path": str(resolved), "filename": resolved.name, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write text content to a file in the sandbox workspace."""
    try:
        resolved = resolve_safe_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(resolved),
            "filename": resolved.name,
            "bytes_written": len(content.encode("utf-8")),
            "summary": f"Wrote {len(content.encode('utf-8'))} bytes to {resolved.name}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_file(path: str) -> dict[str, Any]:
    """Delete a file in the sandbox workspace."""
    try:
        resolved = resolve_safe_path(path)
        if not resolved.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if resolved.is_dir():
            resolved.rmdir()
        else:
            resolved.unlink()
        return {"ok": True, "summary": f"Deleted {resolved.name}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_files(path: str = ".") -> dict[str, Any]:
    """List directory contents in the sandbox workspace."""
    try:
        resolved = resolve_safe_path(path)
        if not resolved.exists():
            return {"ok": False, "error": f"Directory not found: {path}"}

        entries = []
        for item in sorted(resolved.iterdir()):
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "size_bytes": item.stat().st_size if item.is_file() else None,
            })
        return {
            "ok": True,
            "path": str(resolved),
            "entries": entries,
            "summary": f"{len(entries)} items in {resolved.name}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
