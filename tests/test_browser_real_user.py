#!/usr/bin/env python3
"""
Test suite for Real-User Human-like Browser Automation & VM Bridge.
Tests:
- Natural cubic bezier cursor movement and human typing cadences
- Smart login flows with DOM element detection and cookie export
- Authentication session state checking
- Container-to-browser CLI bridge (`azoth-browser`)
- Tool definitions and execution dispatch
"""

import json
import os
import sys
import subprocess
import time
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.browser import get_browser, BROWSER_PROFILE_DIR, WORKSPACE_DIR
from tools.definitions import execute_tool, AGENT_TOOLS
from tools.vm_manager import guest_os


def log_test(name: str, passed: bool, detail: str = ""):
    symbol = "✔" if passed else "✖"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"{color}{symbol} [{name}]{reset} {detail}")


def test_human_interaction(browser):
    """Test human_type and human_click on a mock interactive form."""
    html = """
    <html>
    <head><title>Test Form</title></head>
    <body style="padding: 40px; font-family: sans-serif;">
        <h2>Interactive Form</h2>
        <input id="test-field" type="text" placeholder="Type here..." style="width: 300px; padding: 8px;" />
        <button id="test-submit" onclick="document.getElementById('result').innerText = 'Submitted: ' + document.getElementById('test-field').value;" style="padding: 8px 16px; margin-left: 10px;">Submit</button>
        <div id="result" style="margin-top: 20px; font-weight: bold;">Initial</div>
    </body>
    </html>
    """
    def _setup(p):
        p.goto("about:blank")
        p.set_content(html)
        p.wait_for_load_state("domcontentloaded")
    browser.with_page(_setup)
    
    # 1. Test human typing
    type_res = browser.human_type("#test-field", "Antigravity Agent 2026", press_enter=False)
    input_val = browser.with_page(lambda p: p.evaluate("() => document.getElementById('test-field').value"))
    passed_typing = (type_res.get("ok") is True and input_val == "Antigravity Agent 2026")
    log_test("Human Typing Cadence", passed_typing, f"Typed text matched: '{input_val}' in {type_res.get('duration_ms')}ms")

    # 2. Test human click
    click_res = browser.human_click("#test-submit")
    result_val = browser.with_page(lambda p: p.evaluate("() => document.getElementById('result').innerText"))
    passed_click = (click_res.get("ok") is True and "Antigravity Agent 2026" in result_val)
    log_test("Human Curved Bezier Click", passed_click, f"Result div content: '{result_val}'")

    return passed_typing and passed_click


def test_check_auth(browser):
    """Test checking authentication state on both unauthenticated and authenticated pages."""
    # 1. Test unauthenticated page
    def _setup_unauth(p):
        p.goto("about:blank")
        p.set_content("<html><body><h1>Welcome Guest</h1><a href='/login'>Sign In</a></body></html>")
    browser.with_page(_setup_unauth)
    unauth_res = browser.check_auth()
    passed_unauth = (unauth_res.get("authenticated") is False)
    log_test("Check Auth: Guest Page", passed_unauth, f"Authenticated: {unauth_res.get('authenticated')}")

    # 2. Test page with active session indicator (logout button and profile link)
    auth_html = """
    <html>
    <body>
        <nav>
            <span>Welcome back, @neo</span>
            <a href="/settings/profile" aria-label="Profile">Profile</a>
            <a href="/logout">Log Out</a>
        </nav>
    </body>
    </html>
    """
    browser.with_page(lambda p: p.set_content(auth_html))
    auth_res = browser.check_auth()
    passed_auth = (auth_res.get("authenticated") is True and auth_res.get("user") == "neo")
    log_test("Check Auth: Authenticated Page", passed_auth, f"Authenticated: {auth_res.get('authenticated')}, User: {auth_res.get('user')}")

    return passed_unauth and passed_auth


def test_smart_login(browser):
    """Test smart login auto-detecting credentials and submitting on mock login page."""
    login_html = """
    <html>
    <head><title>Login Page</title></head>
    <body style="padding: 50px;">
        <form id="login-form" onsubmit="event.preventDefault(); document.cookie='session_token=secret_12345; path=/'; document.body.innerHTML = '<h1>Dashboard</h1><a href=/logout>Log Out</a>';">
            <input type="text" id="username" autocomplete="username" placeholder="Username" style="padding: 8px; margin-bottom: 10px;" />
            <br>
            <input type="password" id="password" autocomplete="current-password" placeholder="Password" style="padding: 8px; margin-bottom: 10px;" />
            <br>
            <button type="submit" id="btn-login" style="padding: 8px 16px;">Sign In</button>
        </form>
    </body>
    </html>
    """
    def _setup_login(p):
        p.goto("about:blank")
        p.set_content(login_html)
    browser.with_page(_setup_login)
    
    # Execute smart_login
    login_res = browser.smart_login(
        url="",  # stay on current page
        username="alice",
        password="secretpassword123",
        wait_sec=1
    )
    
    body_content = browser.with_page(lambda p: p.content())
    passed_login = (login_res.get("ok") is True and "Dashboard" in body_content)
    log_test("Smart Login Execution", passed_login, f"Login result: {login_res.get('status') or login_res.get('step')}")
    
    # Check session export
    export_res = browser.export_session()
    export_file = BROWSER_PROFILE_DIR / "session_export.json"
    passed_export = (export_res.get("ok") is True and export_file.exists())
    log_test("Session Cookie Export", passed_export, f"Export ok: {export_res.get('ok')}, file: {export_file.name}")

    return passed_login and passed_export


def test_tool_definitions_and_dispatch():
    """Verify tool schemas exist and execute_tool dispatches correctly."""
    tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
    
    required_tools = [
        "browser_human_click",
        "browser_human_type",
        "browser_login",
        "browser_check_auth",
        "browser_fill_form",
        "browser_takeover"
    ]
    all_registered = all(req in tool_names for req in required_tools)
    log_test("Tool Registration", all_registered, f"Found all {len(required_tools)} browser real-user tools")

    # Dispatch browser_check_auth via execute_tool
    dispatch_res = execute_tool("browser_check_auth", {})
    dispatch_ok = isinstance(dispatch_res, dict) and "authenticated" in dispatch_res
    log_test("Execute Tool: browser_check_auth", dispatch_ok, f"Result keys: {list(dispatch_res.keys()) if isinstance(dispatch_res, dict) else dispatch_res}")

    return all_registered and dispatch_ok


def test_guest_os_browser_cli_bridge():
    """Verify azoth-browser CLI works from host and inside Guest OS container."""
    # 1. Host execution
    cli_path = ROOT / "sandbox" / "workspace" / "azoth-browser"
    assert cli_path.exists(), f"CLI file missing at {cli_path}"
    
    try:
        from tools import browser as _b_mod
        if _b_mod._browser_instance and _b_mod._browser_instance.is_context_alive():
            _b_mod._browser_instance.close()
    except Exception:
        pass

    res = subprocess.run([sys.executable, str(cli_path), "status"], capture_output=True, text=True, timeout=25)
    try:
        host_data = json.loads(res.stdout)
        passed_host_cli = (res.returncode == 0 and ("tabs" in host_data or "url" in host_data or "ok" in host_data))
    except Exception:
        passed_host_cli = False
    log_test("Host CLI Bridge (azoth-browser status)", passed_host_cli, f"Output parsed JSON: {passed_host_cli}")
    assert passed_host_cli, f"Host CLI bridge failed: code={res.returncode}, stdout={res.stdout}, stderr={res.stderr}"

    # 2. Container execution
    container_active = guest_os.is_running()
    if container_active:
        guest_os._ensure_guest_tools()
        vm_res = guest_os.run_command("azoth-browser status", timeout=15)
        try:
            vm_data = json.loads(vm_res.get("stdout", ""))
            passed_vm_cli = (vm_res.get("exit_code") == 0 and ("tabs" in vm_data or "url" in vm_data or "ok" in vm_data))
        except Exception:
            passed_vm_cli = False
        log_test("Guest OS Container CLI (azoth-browser inside VM)", passed_vm_cli, f"Exit code: {vm_res.get('exit_code')}, Parsed JSON: {passed_vm_cli}")
        
        # Test auth check from inside VM
        vm_auth = guest_os.run_command("azoth-browser check-auth", timeout=15)
        try:
            auth_data = json.loads(vm_auth.get("stdout", ""))
            passed_vm_auth = (vm_auth.get("exit_code") == 0 and "authenticated" in auth_data)
        except Exception:
            passed_vm_auth = False
        log_test("Guest OS Container Auth Check (azoth-browser check-auth)", passed_vm_auth, f"Exit code: {vm_auth.get('exit_code')}, Parsed JSON: {passed_vm_auth}")
        return passed_host_cli and passed_vm_cli and passed_vm_auth
    else:
        log_test("Guest OS Container CLI", True, "Skipped container test (backend not active)")
        return passed_host_cli


def run_all_tests():
    print("=" * 65)
    print("  aZoth Real-User Human Browser Automation & VM Bridge Test Suite")
    print("=" * 65)

    browser = get_browser()
    results = []

    try:
        results.append(test_human_interaction(browser))
        results.append(test_check_auth(browser))
        results.append(test_smart_login(browser))
        results.append(test_tool_definitions_and_dispatch())
        results.append(test_guest_os_browser_cli_bridge())
    finally:
        pass

    passed_count = sum(1 for r in results if r)
    total_count = len(results)

    print("-" * 65)
    if passed_count == total_count:
        print(f"\033[92m✔ ALL {total_count} REAL-USER BROWSER TEST GROUPS PASSED!\033[0m")
        return 0
    else:
        print(f"\033[91m✖ {total_count - passed_count} of {total_count} TEST GROUPS FAILED!\033[0m")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
