"""Tests for mature Python code runner features in aZoth-local.

Validates:
- Persistent stateful REPL sessions with session_id support
- ANSI escape sequence stripping from tracebacks and output
- Automatic interception and saving of matplotlib figures/plots as artifacts
- Interactive trailing expression evaluation (Jupyter/IPython style)
- Session isolation, reset, close, and recovery from timeouts
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.code_runner import (
    close_all_sessions,
    close_session,
    list_sessions,
    reset_session,
    run_python,
    strip_ansi,
)
from tools.definitions import AGENT_TOOLS, execute_tool
from tools.workspace import WORKSPACE_DIR
import web_ui


@pytest.fixture(autouse=True)
def cleanup_sessions():
    """Ensure clean sessions and artifacts before and after each test."""
    close_all_sessions()
    test_file = WORKSPACE_DIR / "custom_manual_saved.png"
    if test_file.exists():
        test_file.unlink(missing_ok=True)
    yield
    close_all_sessions()
    if test_file.exists():
        test_file.unlink(missing_ok=True)


class TestStatefulSessions:
    def test_state_persists_across_calls_with_session_id(self):
        sid = "test_persistence"
        res1 = run_python("counter = 100", session_id=sid)
        assert res1["ok"] is True

        res2 = run_python("counter += 25\ncounter", session_id=sid)
        assert res2["ok"] is True
        assert res2["result"] == "125"
        assert "125" in res2["output"]

    def test_function_and_class_persistence(self):
        sid = "test_funcs"
        setup_code = """
class Adder:
    def __init__(self, base):
        self.base = base
    def add(self, n):
        return self.base + n

adder = Adder(50)
"""
        res1 = run_python(setup_code, session_id=sid)
        assert res1["ok"] is True

        res2 = run_python("adder.add(30)", session_id=sid)
        assert res2["ok"] is True
        assert res2["result"] == "80"

    def test_session_isolation(self):
        sid1 = "session_alpha"
        sid2 = "session_beta"

        res1 = run_python("secret_var = 'alpha_value'", session_id=sid1)
        assert res1["ok"] is True

        # In session 2, secret_var should not exist
        res2 = run_python("secret_var", session_id=sid2)
        assert res2["ok"] is False
        assert "NameError" in res2["output"]

        # In session 1, secret_var still exists
        res3 = run_python("secret_var", session_id=sid1)
        assert res3["ok"] is True
        assert res3["result"] == "'alpha_value'"

    def test_ephemeral_sessions_do_not_leak_state(self):
        res1 = run_python("ephemeral_var = 999", session_id=None)
        assert res1["ok"] is True

        res2 = run_python("ephemeral_var", session_id=None)
        assert res2["ok"] is False
        assert "NameError" in res2["output"]

    def test_reset_and_close_session(self):
        sid = "test_lifecycle"
        run_python("v = 42", session_id=sid)
        assert sid in list_sessions()

        reset_ok = reset_session(sid)
        assert reset_ok is True

        # State should be reset
        res_after = run_python("v", session_id=sid)
        assert res_after["ok"] is False

        close_ok = close_session(sid)
        assert close_ok is True
        assert sid not in list_sessions()


class TestAnsiStripping:
    def test_strip_ansi_function(self):
        colored = "\x1b[31mRed\x1b[0m \x1b[1;34mBold Blue\x1b[0m"
        clean = strip_ansi(colored)
        assert clean == "Red Bold Blue"
        assert "\x1b[" not in clean

    def test_traceback_strips_ansi(self):
        code = "raise ValueError('Custom error for ANSI test')"
        res = run_python(code, timeout_sec=5)
        assert res["ok"] is False
        assert "ValueError: Custom error for ANSI test" in res["output"]
        assert "\x1b[" not in res["output"]
        assert "\x1b[" not in res["stderr"]

    def test_stdout_strips_ansi(self):
        code = "print('\\x1b[32mClean Green Output\\x1b[0m')"
        res = run_python(code, timeout_sec=5)
        assert res["ok"] is True
        assert "Clean Green Output" in res["stdout"]
        assert "\x1b[" not in res["stdout"]


class TestTrailingExpressions:
    def test_arithmetic_expression(self):
        res = run_python("a = 15; b = 27\na + b")
        assert res["ok"] is True
        assert res["result"] == "42"
        assert "42" in res["output"]

    def test_string_expression(self):
        res = run_python("'hello' + ' ' + 'world'")
        assert res["ok"] is True
        assert res["result"] == "'hello world'"
        assert "'hello world'" in res["output"]

    def test_list_and_dict_expression(self):
        res = run_python("[x * 2 for x in range(4)]")
        assert res["ok"] is True
        assert res["result"] == "[0, 2, 4, 6]"

        res_dict = run_python("{'status': 'ok', 'code': 200}")
        assert res_dict["ok"] is True
        assert "'status': 'ok'" in res_dict["result"]

    def test_assignment_has_no_trailing_expression(self):
        res = run_python("z = 100")
        assert res["ok"] is True
        assert res["result"] is None

    def test_none_expression_does_not_print_none(self):
        res = run_python("print('Line 1')")
        assert res["ok"] is True
        assert res["result"] is None
        assert "Line 1" in res["output"]
        assert "None" not in res["output"]


class TestMatplotlibArtifacts:
    def test_intercept_plot_with_show(self):
        code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [4, 5, 6])
plt.title('Show Intercept Test')
plt.show()
"""
        res = run_python(code, session_id="mpl_show_sess")
        assert res["ok"] is True
        assert len(res["artifacts"]) >= 1
        art = res["artifacts"][0]
        assert art["filename"].endswith(".png")
        assert Path(art["path"]).is_file()
        assert art["size_bytes"] > 0
        assert art["relative_path"] in res["plots"]

    def test_intercept_plot_without_show(self):
        code = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.bar(['x', 'y'], [5, 10])
ax.set_title('No Show Test')
"""
        res = run_python(code, session_id="mpl_noshow_sess")
        assert res["ok"] is True
        assert len(res["artifacts"]) >= 1
        art = res["artifacts"][0]
        assert Path(art["path"]).is_file()
        assert art["size_bytes"] > 0

    def test_figure_as_trailing_expression(self):
        code = """
import matplotlib.pyplot as plt
fig = plt.figure()
plt.plot([10, 20], [30, 40])
fig
"""
        res = run_python(code, session_id="mpl_expr_sess")
        assert res["ok"] is True
        assert len(res["artifacts"]) >= 1
        assert "<Figure" in str(res["result"])

    def test_manual_savefig_detected_as_artifact(self):
        code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2], [3, 4])
plt.savefig('custom_manual_saved.png')
plt.close('all')
"""
        res = run_python(code, session_id="mpl_manual_sess")
        assert res["ok"] is True
        assert any("custom_manual_saved.png" in a["filename"] for a in res["artifacts"])
        saved_file = WORKSPACE_DIR / "custom_manual_saved.png"
        assert saved_file.exists()


class TestTimeoutAndRecovery:
    def test_timeout_and_automatic_recovery(self):
        sid = "timeout_session"

        # Initialize variable in session
        res0 = run_python("init_var = 77", session_id=sid)
        assert res0["ok"] is True

        # Run code that times out
        res_timeout = run_python("import time; time.sleep(10)", timeout_sec=1, session_id=sid)
        assert res_timeout["ok"] is False
        assert "timed out" in res_timeout["error"].lower()

        # Session process was killed; next call should recover and run without hanging
        res_recover = run_python("recovered = True\nrecovered", session_id=sid)
        assert res_recover["ok"] is True
        assert res_recover["result"] == "True"


class TestToolDefinitionsAndWebUI:
    def test_execute_tool_with_session(self):
        # 1. Store in session
        res1 = execute_tool("python_repl", {"code": "x_tool = 55", "session_id": "tool_sess"})
        assert res1["ok"] is True

        # 2. Access in session
        res2 = execute_tool("python_repl", {"code": "x_tool * 2", "session_id": "tool_sess"})
        assert res2["ok"] is True
        assert res2["result"] == "110"

    def test_web_ui_endpoints(self):
        client = TestClient(web_ui.app)

        # Stateful run via Web UI
        r1 = client.post("/api/python/run", json={"code": "web_x = 90", "session_id": "web_sess"})
        assert r1.status_code == 200
        assert r1.json()["ok"] is True

        r2 = client.post("/api/python/run", json={"code": "web_x + 10", "session_id": "web_sess"})
        assert r2.status_code == 200
        assert r2.json()["result"] == "100"

        # Reset endpoint
        r3 = client.post("/api/python/reset", json={"session_id": "web_sess"})
        assert r3.status_code == 200
        assert r3.json()["ok"] is True

        # State should now be reset
        r4 = client.post("/api/python/run", json={"code": "web_x", "session_id": "web_sess"})
        assert r4.status_code == 200
        assert r4.json()["ok"] is False
