"""Automated Test Suite for DuckyScript Engine & Macro Suite."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.duckyscript import (
    DUCKY_PRESETS,
    DuckyScriptEngine,
    expand_variables,
    get_ducky_engine,
    get_recovery_suggestion,
    load_all_presets,
    parse_var_declaration,
    run_duckyscript,
)


class MockSandboxBrowser:
    """Mock SandboxBrowser for fast, deterministic unit testing."""

    def __init__(self):
        self.typed_texts: list[str] = []
        self.pressed_keys: list[str] = []
        self.navigated_urls: list[str] = []
        self.clicks: list[Any] = []
        self.mouse_moves: list[tuple[int, int]] = []
        self.scrolls: list[int] = []
        self.screenshots: list[str] = []
        self.wait_fors: list[tuple[str, int]] = []
        self.tabs: list[dict[str, Any]] = [{"index": 0, "title": "Tab 0", "url": "https://google.com"}]
        self.active_page_index: int = 0

    def keyboard_type(self, text: str) -> dict[str, Any]:
        self.typed_texts.append(text)
        return {"ok": True, "text": text}

    def keyboard_press(self, key: str) -> dict[str, Any]:
        self.pressed_keys.append(key)
        return {"ok": True, "key": key}

    def navigate(self, url: str) -> dict[str, Any]:
        self.navigated_urls.append(url)
        return {"ok": True, "url": url}

    def new_tab(self, url: str = "https://google.com") -> dict[str, Any]:
        self.tabs.append({"index": len(self.tabs), "title": "New Tab", "url": url})
        self.active_page_index = len(self.tabs) - 1
        return {"ok": True, "active_tab": self.active_page_index, "tabs": self.tabs}

    def list_tabs(self) -> list[dict[str, Any]]:
        return self.tabs

    def close_tab(self, index: int) -> dict[str, Any]:
        if 0 <= index < len(self.tabs):
            self.tabs.pop(index)
            self.active_page_index = max(0, min(self.active_page_index, len(self.tabs) - 1))
        return {"ok": True, "tabs": self.tabs}

    def mouse_click(self, x: int, y: int) -> dict[str, Any]:
        self.clicks.append((x, y))
        return {"ok": True, "x": x, "y": y}

    def click(self, selector: str) -> dict[str, Any]:
        if "error_trigger" in selector:
            return {"ok": False, "error": f"Element '{selector}' was not found"}
        self.clicks.append(selector)
        return {"ok": True, "selector": selector}

    def mouse_move(self, x: int, y: int) -> dict[str, Any]:
        self.mouse_moves.append((x, y))
        return {"ok": True, "x": x, "y": y}

    def mouse_wheel(self, delta_x: int = 0, delta_y: int = 200) -> dict[str, Any]:
        self.scrolls.append(delta_y)
        return {"ok": True, "delta_y": delta_y}

    def screenshot(self, filename: str) -> dict[str, Any]:
        self.screenshots.append(filename)
        p = Path(filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRmock_data")
        return {"ok": True, "path": str(p), "filename": p.name}

    def wait_for(self, selector_or_text: str, timeout_ms: int = 10000) -> dict[str, Any]:
        if "timeout_fail" in selector_or_text:
            return {"ok": False, "error": f"Timeout waiting for '{selector_or_text}' after {timeout_ms}ms"}
        self.wait_fors.append((selector_or_text, timeout_ms))
        return {"ok": True, "target": selector_or_text}

    @property
    def current_page(self):
        parent = self

        class MockPage:
            class MockKeyboard:
                def press(self, key: str):
                    parent.pressed_keys.append(key)

            def __init__(self):
                self.keyboard = self.MockKeyboard()

            def screenshot(self, path: str, full_page: bool = False):
                parent.screenshot(path)

            def click(self, selector: str):
                parent.click(selector)

        return MockPage()


@pytest.fixture
def mock_engine():
    browser = MockSandboxBrowser()
    engine = DuckyScriptEngine(browser_instance=browser)
    return engine, browser


# =============================================================================
# 1. Variable Assignment and Substitution Tests
# =============================================================================
class TestVariables:
    def test_parse_var_declaration(self):
        assert parse_var_declaration("SEARCH=hvac contractors") == ("SEARCH", "hvac contractors")
        assert parse_var_declaration('POST_TEXT="Hello World"') == ("POST_TEXT", "Hello World")
        assert parse_var_declaration("CITY = 'Virginia Beach'") == ("CITY", "Virginia Beach")
        assert parse_var_declaration("UNSET_VAR") == ("UNSET_VAR", "")

    def test_expand_variables_simple(self):
        vars_dict = {"NAME": "Alice", "CITY": "Norfolk"}
        expanded = expand_variables("STRING Hello $NAME in $CITY!", vars_dict)
        assert expanded == "STRING Hello Alice in Norfolk!"

    def test_expand_variables_curly(self):
        vars_dict = {"DOMAIN": "github.com", "USER": "neal"}
        expanded = expand_variables("NAVIGATE https://${DOMAIN}/${USER}", vars_dict)
        assert expanded == "NAVIGATE https://github.com/neal"

    def test_built_in_variables(self):
        expanded = expand_variables("LOG Running on $DATE with random $RANDOM", {})
        assert "$DATE" not in expanded
        assert "$RANDOM" not in expanded

    def test_var_execution_in_engine(self, mock_engine):
        engine, browser = mock_engine
        script = """
VAR USERNAME=alpha_coder
VAR TARGET_URL=https://example.com/user/$USERNAME
NAVIGATE $TARGET_URL
STRING Welcome $USERNAME
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert browser.navigated_urls == ["https://example.com/user/alpha_coder"]
        assert browser.typed_texts == ["Welcome alpha_coder"]
        assert res["vars"]["USERNAME"] == "alpha_coder"


# =============================================================================
# 2. Timing & Random Delay Tests
# =============================================================================
class TestDelays:
    def test_delay_command(self, mock_engine):
        engine, _ = mock_engine
        script = """
DELAY 20
LOG Delay step done
"""
        start = time.time()
        res = engine.execute(script, target="browser")
        duration = time.time() - start
        assert res["ok"] is True
        assert duration >= 0.015
        assert any("DELAY 20ms" in s for s in res["executed_steps"])

    def test_random_delay_command(self, mock_engine):
        engine, _ = mock_engine
        script = """
RANDOM_DELAY 10 30
LOG Random delay step done
"""
        start = time.time()
        res = engine.execute(script, target="browser")
        duration = time.time() - start
        assert res["ok"] is True
        assert duration >= 0.008
        assert any("RANDOM_DELAY" in s for s in res["executed_steps"])


# =============================================================================
# 3. Dynamic DOM Synchronization (WAIT_FOR) Tests
# =============================================================================
class TestWaitFor:
    def test_wait_for_success(self, mock_engine):
        engine, browser = mock_engine
        script = """
WAIT_FOR input[name="q"] 5000
STRING test search
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert browser.wait_fors == [('input[name="q"]', 5000)]
        assert browser.typed_texts == ["test search"]

    def test_wait_for_timeout_failure_and_suggestion(self, mock_engine):
        engine, _ = mock_engine
        script = """
LOG Starting search
WAIT_FOR div.timeout_fail 3000
STRING should not run
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is False
        assert res["line_number"] == 3
        assert res["command"] == "WAIT_FOR"
        assert "timeout_fail" in res["error"]
        assert "Suggestions:" in res["suggestion"]
        assert "Increase the timeout" in res["suggestion"]


# =============================================================================
# 4. State Capture (SCREENSHOT) Tests
# =============================================================================
class TestScreenshot:
    def test_screenshot_command(self, mock_engine, tmp_path):
        engine, browser = mock_engine
        screenshot_file = tmp_path / "test_capture.png"
        script = f"""
VAR CAPTURE_FILE={screenshot_file}
SCREENSHOT $CAPTURE_FILE
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert screenshot_file.exists()
        assert any("SCREENSHOT -> test_capture.png" in s for s in res["executed_steps"])


# =============================================================================
# 5. Modular Composition (REPLAY) Tests
# =============================================================================
class TestReplay:
    def test_replay_preset_by_id(self, mock_engine):
        engine, browser = mock_engine
        script = """
VAR SEARCH_TERM=plumbers in norfolk
REPLAY google_scrape
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert any("https://www.google.com" in url for url in browser.navigated_urls)
        assert any("plumbers in norfolk" in t for t in browser.typed_texts)

    def test_replay_nested_with_variables(self, mock_engine, tmp_path):
        engine, browser = mock_engine
        sub_macro = tmp_path / "sub_macro.ducky"
        sub_macro.write_text("""
LOG Running sub macro
STRING SubMacro: $GREETING
""", encoding="utf-8")

        main_script = f"""
VAR GREETING=HelloFromParent
REPLAY {sub_macro}
"""
        res = engine.execute(main_script, target="browser")
        assert res["ok"] is True
        assert browser.typed_texts == ["SubMacro: HelloFromParent"]
        assert any("[sub_macro] STRING 'SubMacro: HelloFromParent'" in s for s in res["executed_steps"])

    def test_replay_circular_recursion_detection(self, mock_engine, tmp_path):
        engine, _ = mock_engine
        macro_a = tmp_path / "macro_a.ducky"
        macro_b = tmp_path / "macro_b.ducky"

        macro_a.write_text(f"REPLAY {macro_b}", encoding="utf-8")
        macro_b.write_text(f"REPLAY {macro_a}", encoding="utf-8")

        res = engine.execute(f"REPLAY {macro_a}", target="browser")
        assert res["ok"] is False
        assert "Circular REPLAY" in res["error"] or "Recursion" in res["error"]
        assert "suggestion" in res


# =============================================================================
# 6. Keyboard, Mouse, and Browser Navigation Commands
# =============================================================================
class TestCoreCommands:
    def test_keyboard_keys_and_shortcuts(self, mock_engine):
        engine, browser = mock_engine
        script = """
STRING AlphaBot
ENTER
TAB
SPACE
ESCAPE
BACKSPACE
DOWN
UP
CTRL+T https://example.com
CTRL+W
CTRL+L
CTRL+V
CTRL+C
CTRL+A
CTRL+ENTER
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert "AlphaBot" in browser.typed_texts
        assert "Enter" in browser.pressed_keys
        assert "Tab" in browser.pressed_keys
        assert " " in browser.pressed_keys
        assert "Escape" in browser.pressed_keys
        assert "Backspace" in browser.pressed_keys
        assert "ArrowDown" in browser.pressed_keys
        assert "ArrowUp" in browser.pressed_keys
        assert "Control+L" in browser.pressed_keys
        assert "Control+V" in browser.pressed_keys
        assert "Control+C" in browser.pressed_keys
        assert "Control+A" in browser.pressed_keys
        assert "Control+Enter" in browser.pressed_keys

    def test_mouse_clicks_and_scroll(self, mock_engine):
        engine, browser = mock_engine
        script = """
CLICK 450 300
CLICK button#submit
MOUSE_MOVE 100 200
SCROLL 400
SCROLL -200
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert (450, 300) in browser.clicks
        assert "button#submit" in browser.clicks
        assert (100, 200) in browser.mouse_moves
        assert 400 in browser.scrolls
        assert -200 in browser.scrolls

    def test_repeat_command(self, mock_engine):
        engine, browser = mock_engine
        script = """
STRING tick
REPEAT 3
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        # Original 1 + repeated 3 = 4 total
        assert browser.typed_texts == ["tick", "tick", "tick", "tick"]


# =============================================================================
# 7. Error Reporting and Recovery Suggestions Tests
# =============================================================================
class TestErrorDiagnostics:
    def test_unknown_command_error(self, mock_engine):
        engine, _ = mock_engine
        script = """
REM Valid header
DELAY 10
INVALID_COMMAND_XYZ foo bar
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is False
        assert res["line_number"] == 4
        assert res["command"] == "INVALID_COMMAND_XYZ"
        assert "Unrecognized DuckyScript command" in res["error"]
        assert "Suggestions:" in res["suggestion"]

    def test_invalid_var_error(self, mock_engine):
        engine, _ = mock_engine
        script = "VAR"
        res = engine.execute(script, target="browser")
        assert res["ok"] is False
        assert res["line_number"] == 1
        assert res["command"] == "VAR"
        assert "VAR requires" in res["error"]

    def test_click_target_failure_suggestion(self, mock_engine):
        engine, _ = mock_engine
        script = "CLICK error_trigger"
        res = engine.execute(script, target="browser")
        assert res["ok"] is False
        assert res["command"] == "CLICK"
        assert "Suggestions:" in res["suggestion"]
        assert "WAIT_FOR" in res["suggestion"]


# =============================================================================
# 8. Presets Library Discovery & Verification Tests
# =============================================================================
class TestPresetsLibrary:
    def test_presets_loaded(self):
        presets = load_all_presets()
        preset_ids = {p["id"] for p in presets}
        expected_ids = {
            "x_post",
            "linkedin_outreach",
            "google_scrape",
            "github_workflow",
            "local_service_lead_grabber",
            "tab_cycle",
            "scroll_reader",
        }
        for eid in expected_ids:
            assert eid in preset_ids, f"Preset '{eid}' missing from loaded presets"

    def test_all_presets_validate_cleanly(self):
        engine = get_ducky_engine()
        presets = load_all_presets()
        assert len(presets) >= 5
        for p in presets:
            val_res = engine.validate(p["template"])
            assert val_res["valid"] is True, f"Preset '{p['id']}' failed validation: {val_res.get('errors')}"
            assert val_res["total_lines"] > 0


# =============================================================================
# 9. CLI Utility (tools/ducky_cli.py) Integration Tests
# =============================================================================
class TestCLI:
    def test_cli_list_presets(self):
        cli_path = ROOT / "tools" / "ducky_cli.py"
        res = subprocess.run(
            [sys.executable, str(cli_path), "--list-presets", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        assert data["ok"] is True
        ids = [p["id"] for p in data["presets"]]
        assert "x_post" in ids
        assert "google_scrape" in ids
        assert "linkedin_outreach" in ids

    def test_cli_validate_preset(self):
        cli_path = ROOT / "tools" / "ducky_cli.py"
        preset_path = ROOT / "tools" / "presets" / "google_scrape.ducky"
        res = subprocess.run(
            [sys.executable, str(cli_path), "--file", str(preset_path), "--validate", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        assert data["ok"] is True
        assert data["valid"] is True

    def test_cli_validate_inline_invalid_script(self):
        cli_path = ROOT / "tools" / "ducky_cli.py"
        res = subprocess.run(
            [sys.executable, str(cli_path), "BOGUS_CMD_ABC", "--validate", "--json"],
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        data = json.loads(res.stdout)
        assert data["valid"] is False
        assert len(data["errors"]) > 0


# =============================================================================
# 10. Agent Tool Dispatch & OS Target Tests
# =============================================================================
class TestAgentToolDispatch:
    def test_execute_tool_with_vars(self, monkeypatch):
        from tools.definitions import execute_tool
        mock_browser = MockSandboxBrowser()
        engine = DuckyScriptEngine(browser_instance=mock_browser)
        monkeypatch.setattr("tools.duckyscript.get_ducky_engine", lambda: engine)
        monkeypatch.setattr("tools.definitions.run_duckyscript", lambda script, target="browser", vars=None: engine.execute(script, target=target, vars=vars))

        res = execute_tool(
            "duckyscript",
            {
                "script": "VAR SEARCH=azoth\nNAVIGATE https://google.com?q=$SEARCH\nSTRING $SEARCH",
                "vars": {"SEARCH": "enterprise_automation"},
            },
        )
        assert res["ok"] is True
        assert mock_browser.navigated_urls == ["https://google.com?q=enterprise_automation"]
        assert mock_browser.typed_texts == ["enterprise_automation"]

    def test_os_target_execution(self):
        engine = DuckyScriptEngine()
        script = """
VAR TEST_VAR=desktop_test
LOG OS target simulation
DELAY 10
RANDOM_DELAY 10 20
SCREENSHOT test_os_capture.png
"""
        res = engine.execute(script, target="os")
        assert res["ok"] is True
        assert res["vars"]["TEST_VAR"] == "desktop_test"
        assert any("SCREENSHOT" in s for s in res["executed_steps"])

    def test_extended_nav_keys(self, mock_engine):
        engine, browser = mock_engine
        script = """
PAGE_UP
PAGE_DOWN
HOME
END
LEFT
RIGHT
"""
        res = engine.execute(script, target="browser")
        assert res["ok"] is True
        assert "ArrowLeft" in browser.pressed_keys
        assert "ArrowRight" in browser.pressed_keys

