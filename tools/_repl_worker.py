"""Background worker process for persistent stateful Python REPL sessions in aZoth-local.

Runs inside the sandbox workspace environment:
- Maintains a persistent execution namespace for stateful REPL sessions
- Evaluates trailing expressions (Jupyter / IPython style)
- Automatically intercepts and saves matplotlib figures and plots as artifacts
- Strips ANSI escape sequences from standard streams and tracebacks
- Communicates with the parent process via JSON lines over stdio
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Ensure headless execution and disable ANSI colors from runtime
os.environ["MPLBACKEND"] = "Agg"
os.environ["PYTHON_COLORS"] = "0"
os.environ["NO_COLOR"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal and traceback text."""
    if not text:
        return ""
    return ANSI_ESCAPE_RE.sub("", text)


WORKSPACE_DIR = Path(os.environ.get("AZOTH_WORKSPACE_DIR", os.getcwd())).resolve()
ARTIFACTS_DIR = WORKSPACE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Add workspace directory to sys.path so user scripts can import local modules
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except Exception:
    plt = None
    Figure = None

# Global execution state for this REPL session
session_globals: dict[str, Any] = {
    "__name__": "__main__",
    "__doc__": None,
}

plot_counter = 0
current_artifacts: list[dict[str, Any]] = []
current_session_id = "default"


def _record_artifact_file(filepath: Path) -> None:
    """Helper to register an image/plot file in current_artifacts."""
    global current_artifacts
    try:
        p = filepath.resolve()
        if p.is_file() and not any(a["path"] == str(p) for a in current_artifacts):
            try:
                rel = str(p.relative_to(WORKSPACE_DIR))
            except ValueError:
                rel = p.name
            current_artifacts.append({
                "type": f"image/{p.suffix.lower().lstrip('.') or 'png'}",
                "filename": p.name,
                "path": str(p),
                "relative_path": rel,
                "size_bytes": p.stat().st_size,
            })
    except Exception:
        pass


def _hook_figure_class(fig_cls: Any) -> None:
    """Hook Figure.savefig to intercept explicit savefig calls."""
    if hasattr(fig_cls, "savefig"):
        orig_savefig = fig_cls.savefig
        if getattr(orig_savefig, "__name__", "") == "_hooked_figure_savefig":
            return

        def _hooked_figure_savefig(self: Any, fname: Any, *args: Any, **kwargs: Any) -> Any:
            res = orig_savefig(self, fname, *args, **kwargs)
            if isinstance(fname, (str, Path, os.PathLike)):
                p = Path(fname)
                if not p.is_absolute():
                    p = (WORKSPACE_DIR / p).resolve()
                _record_artifact_file(p)
            return res

        fig_cls.savefig = _hooked_figure_savefig


if Figure is not None:
    _hook_figure_class(Figure)


def _capture_figures(session_id: str) -> list[dict[str, Any]]:
    """Capture all open matplotlib figures, save them to ARTIFACTS_DIR, and close them."""
    global plot_counter, plt
    captured: list[dict[str, Any]] = []
    m_plt = sys.modules.get("matplotlib.pyplot") or plt
    if m_plt is None:
        return captured

    try:
        fignums = m_plt.get_fignums()
        for fignum in fignums:
            fig = m_plt.figure(fignum)
            plot_counter += 1
            ts = int(time.time() * 1000)
            safe_session = "".join(c for c in session_id if c.isalnum() or c in "_-") or "repl"
            filename = f"plot_{safe_session}_{ts}_{plot_counter}.png"
            filepath = ARTIFACTS_DIR / filename
            fig.savefig(str(filepath), bbox_inches="tight", dpi=150)
            m_plt.close(fig)

            captured.append({
                "type": "image/png",
                "filename": filename,
                "path": str(filepath.resolve()),
                "relative_path": str(filepath.relative_to(WORKSPACE_DIR)),
                "size_bytes": filepath.stat().st_size,
            })
    except Exception:
        pass
    return captured


def _intercept_show(*args: Any, **kwargs: Any) -> None:
    """Monkey-patched plt.show() that captures figures immediately."""
    global current_artifacts, current_session_id
    arts = _capture_figures(current_session_id)
    current_artifacts.extend(arts)


# Pre-hook plt.show if matplotlib is installed
if plt is not None:
    plt.show = _intercept_show


def execute_snippet(code: str, session_id: str) -> dict[str, Any]:
    """Execute a Python snippet within this stateful session."""
    global current_artifacts, current_session_id
    current_session_id = session_id
    current_artifacts = []

    # Ensure plt.show and Figure.savefig are hooked if matplotlib was imported
    if "matplotlib.pyplot" in sys.modules:
        sys.modules["matplotlib.pyplot"].show = _intercept_show
    if "matplotlib.figure" in sys.modules:
        _hook_figure_class(sys.modules["matplotlib.figure"].Figure)

    # Snapshot existing files in workspace with mtime to detect newly generated or updated files
    existing_files: dict[Path, int] = {}
    try:
        for p in WORKSPACE_DIR.glob("**/*"):
            if p.is_file():
                existing_files[p.resolve()] = p.stat().st_mtime_ns
    except Exception:
        pass

    start_time = time.perf_counter()

    # Capture stdout and stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    buf_stdout = io.StringIO()
    buf_stderr = io.StringIO()
    sys.stdout = buf_stdout
    sys.stderr = buf_stderr

    ok = True
    result_repr: str | None = None
    error_msg: str | None = None
    returncode = 0

    try:
        tree = ast.parse(code)
        if not tree.body:
            pass
        elif isinstance(tree.body[-1], ast.Expr):
            # Split off trailing expression for interactive evaluation
            exec_mod = ast.Module(body=tree.body[:-1], type_ignores=[])
            eval_mod = ast.Expression(body=tree.body[-1].value)

            exec_code = compile(exec_mod, filename="<azoth-repl>", mode="exec")
            eval_code = compile(eval_mod, filename="<azoth-repl>", mode="eval")

            exec(exec_code, session_globals)
            result_val = eval(eval_code, session_globals)
            if result_val is not None:
                result_repr = repr(result_val)
        else:
            exec_code = compile(tree, filename="<azoth-repl>", mode="exec")
            exec(exec_code, session_globals)

    except SystemExit as se:
        ok = False
        returncode = se.code if isinstance(se.code, int) else 1
        error_msg = f"SystemExit({se.code})"
        buf_stderr.write(f"SystemExit: {se.code}\n")
    except Exception as e:
        ok = False
        returncode = 1
        error_msg = str(e)
        buf_stderr.write(traceback.format_exc())
    finally:
        # 1. Capture any unclosed matplotlib figures
        open_fig_arts = _capture_figures(session_id)
        current_artifacts.extend(open_fig_arts)

        # 2. Check for any newly created or updated image/plot files in workspace
        try:
            for p in sorted(WORKSPACE_DIR.glob("**/*")):
                if p.is_file():
                    rp = p.resolve()
                    prev_mtime = existing_files.get(rp)
                    if prev_mtime is None or p.stat().st_mtime_ns > prev_mtime:
                        if rp.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".webp"}:
                            _record_artifact_file(rp)
        except Exception:
            pass

        # Restore streams
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    elapsed = round(time.perf_counter() - start_time, 3)

    raw_stdout = strip_ansi(buf_stdout.getvalue())
    raw_stderr = strip_ansi(buf_stderr.getvalue())

    # Build clean output display
    output_display = raw_stdout
    if result_repr is not None:
        if output_display and not output_display.endswith("\n"):
            output_display += "\n"
        output_display += result_repr

    if raw_stderr:
        if output_display:
            output_display += "\n\n[STDERR]:\n" + raw_stderr
        else:
            output_display = raw_stderr

    plots = [a["relative_path"] for a in current_artifacts]

    summary = (
        f"Python executed in {elapsed}s (exit {returncode})"
        if ok
        else f"Python failed with code {returncode} in {elapsed}s"
    )

    resp: dict[str, Any] = {
        "ok": ok,
        "returncode": returncode,
        "elapsed_seconds": elapsed,
        "stdout": raw_stdout,
        "stderr": raw_stderr,
        "result": result_repr,
        "output": output_display,
        "artifacts": current_artifacts,
        "plots": plots,
        "session_id": session_id,
        "summary": summary,
    }
    if error_msg:
        resp["error"] = error_msg
    return resp


def main() -> None:
    """Worker main loop reading JSON commands from stdin and replying on stdout."""
    real_stdout = sys.__stdout__
    real_stdin = sys.__stdin__

    while True:
        line = real_stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            action = req.get("action", "execute")
            if action == "ping":
                resp: dict[str, Any] = {"ok": True, "pong": True}
            elif action == "reset":
                session_globals.clear()
                session_globals.update({"__name__": "__main__", "__doc__": None})
                m_plt = sys.modules.get("matplotlib.pyplot") or plt
                if m_plt is not None:
                    m_plt.close("all")
                resp = {"ok": True, "reset": True}
            else:
                code = req.get("code", "")
                session_id = req.get("session_id", "default")
                resp = execute_snippet(code, session_id)
        except Exception as e:
            err_tb = strip_ansi(traceback.format_exc())
            resp = {
                "ok": False,
                "returncode": 1,
                "error": str(e),
                "stderr": err_tb,
                "output": err_tb,
                "summary": f"Execution error: {e}",
            }

        real_stdout.write("__AZOTH_REPL_RESULT__:" + json.dumps(resp) + "\n")
        real_stdout.flush()


if __name__ == "__main__":
    main()
