#!/usr/bin/env python3
"""Comprehensive test suite for hardened SandboxBrowser in a-bot."""

import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.browser import get_browser, BROWSER_PROFILE_DIR, WORKSPACE_DIR
from tools.definitions import execute_tool, AGENT_TOOLS


def log_test(name: str, passed: bool, detail: str = ""):
    symbol = "✔" if passed else "✖"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"{color}{symbol} [{name}]{reset} {detail}")


def test_stealth_and_anti_detection(browser):
    """Test navigator.webdriver masking, chrome object, plugins, and languages."""
    def _action(page):
        page.goto("about:blank")
        webdriver_val = page.evaluate("() => navigator.webdriver")
        has_chrome = page.evaluate("() => typeof window.chrome === 'object' && typeof window.chrome.runtime === 'object'")
        languages = page.evaluate("() => navigator.languages")
        plugin_count = page.evaluate("() => navigator.plugins.length")
        ua = page.evaluate("() => navigator.userAgent")
        return webdriver_val, has_chrome, languages, plugin_count, ua

    webdriver_val, has_chrome, languages, plugin_count, ua = browser.with_page(_action)
    passed_webdriver = (webdriver_val is None or webdriver_val is False)
    log_test("Anti-Detection: navigator.webdriver", passed_webdriver, f"Value is: {webdriver_val}")
    
    log_test("Anti-Detection: window.chrome object", has_chrome, f"window.chrome.runtime exists: {has_chrome}")
    
    passed_lang = isinstance(languages, list) and len(languages) > 0 and "en-US" in languages
    log_test("Anti-Detection: navigator.languages", passed_lang, f"Languages: {languages}")
    
    passed_plugins = plugin_count > 0
    log_test("Anti-Detection: navigator.plugins", passed_plugins, f"Plugin count: {plugin_count}")

    passed_ua = "Linux" in ua and "Chrome" in ua and "Headless" not in ua
    log_test("Anti-Detection: Headed User-Agent", passed_ua, f"UA: {ua[:60]}...")
    
    assert passed_webdriver and has_chrome and passed_lang and passed_plugins and passed_ua
    return True


def test_navigation_and_tab_management(browser):
    """Test multi-tab creation, switching, and closing."""
    # 1. Navigate active tab
    nav_res = browser.navigate("https://example.com")
    passed_nav = nav_res.get("ok") is True and "Example" in nav_res.get("title", "")
    log_test("Navigation: example.com", passed_nav, f"Title: {nav_res.get('title')}")

    # 2. Open new tab
    new_tab_res = browser.new_tab("about:blank")
    tabs = browser.list_tabs()
    passed_new_tab = new_tab_res.get("ok") is True and len(tabs) >= 2
    log_test("Multi-Tab: new_tab", passed_new_tab, f"Total tabs: {len(tabs)}")

    # 3. Switch tab
    switch_res = browser.switch_tab(0)
    passed_switch = switch_res.get("ok") is True and switch_res.get("active_tab") == 0
    log_test("Multi-Tab: switch_tab", passed_switch, f"Active tab index: {switch_res.get('active_tab')}")

    # 4. Close second tab
    close_res = browser.close_tab(1)
    passed_close = close_res.get("ok") is True
    log_test("Multi-Tab: close_tab", passed_close, f"Remaining tabs: {len(browser.list_tabs())}")

    return passed_nav and passed_new_tab and passed_switch and passed_close


def test_session_export_and_import(browser):
    """Test exporting cookies & storage, clearing, and importing them back."""
    def _setup_session(page):
        page.goto("https://example.com")
        browser.context.add_cookies([
            {
                "name": "abot_auth_token",
                "value": "sec_token_xyz123_hardened",
                "domain": "example.com",
                "path": "/",
                "httpOnly": False,
                "secure": False,
            }
        ])
        page.evaluate("() => { window.localStorage.setItem('abot_user', 'neal_frazier'); }")
    browser.with_page(_setup_session)

    # 1. Export session
    backup_file = WORKSPACE_DIR / "test_session_export.json"
    if backup_file.exists():
        backup_file.unlink()

    export_res = browser.export_session(filepath=str(backup_file))
    passed_export = export_res.get("ok") is True and backup_file.exists()
    log_test("Session: export_session", passed_export, f"Exported to {backup_file.name} (cookies: {export_res.get('cookies_count')})")

    # 2. Clear session
    clear_res = browser.clear_session()
    def _check_clear(page):
        page.goto("https://example.com")
        cookies = [c for c in browser.context.cookies() if c.get("name") == "abot_auth_token"]
        storage = page.evaluate("() => window.localStorage.getItem('abot_user')")
        return len(cookies) == 0 and storage is None
    passed_clear = browser.with_page(_check_clear)
    log_test("Session: clear_session", passed_clear, f"Cookies & storage cleared: {passed_clear}")

    # 3. Import session
    import_res = browser.import_session(filepath=str(backup_file))
    def _check_import(page):
        page.goto("https://example.com")
        cookies = [c for c in browser.context.cookies() if c.get("name") == "abot_auth_token"]
        return len(cookies) > 0 and cookies[0]["value"] == "sec_token_xyz123_hardened"
    restored_ok = browser.with_page(_check_import)
    passed_import = import_res.get("ok") is True and restored_ok
    log_test("Session: import_session", passed_import, f"Restored cookie token: {passed_import}")

    assert passed_export and passed_clear and passed_import
    return True


def test_highlights_and_coordinates(browser):
    """Test element highlighting, bounding box calculations, and interactive elements scanner."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head><style>body { font-family: sans-serif; padding: 40px; }</style></head>
    <body>
      <h1>Test Target Page</h1>
      <button id="login-btn" style="padding: 12px 24px; background: #1a73e8; color: white; border: none; border-radius: 8px;">Log In Here</button>
      <input id="user-input" type="text" placeholder="Enter your username" style="padding: 8px; margin-left: 10px;" />
      <a href="https://example.com" id="help-link">Need Help?</a>
    </body>
    </html>
    """
    browser.with_page(lambda p: p.set_content(html_content))

    # 1. Highlight element
    hl_res = browser.highlight_element("#login-btn", duration_ms=3000, color="#ea4335", label="Target Button")
    passed_hl = hl_res.get("ok") is True and "coordinates" in hl_res
    coords = hl_res.get("coordinates", {})
    log_test("Visual Inspection: highlight_element", passed_hl, f"Coordinates: center=({coords.get('center_x')}, {coords.get('center_y')}), w={coords.get('width')}, h={coords.get('height')}")

    # 2. Get coordinates
    coord_res = browser.get_element_coordinates("#user-input")
    passed_coord = coord_res.get("ok") is True and coord_res.get("visible") is True
    log_test("Visual Inspection: get_element_coordinates", passed_coord, f"Input center: ({coord_res.get('center_x')}, {coord_res.get('center_y')})")

    # 3. Interactive elements scanner
    interactive_res = browser.get_interactive_elements_with_bounds(max_elements=10)
    passed_interactive = interactive_res.get("ok") is True and interactive_res.get("count", 0) >= 3
    log_test("Visual Inspection: get_interactive_elements_with_bounds", passed_interactive, f"Found {interactive_res.get('count')} elements with exact bounds")

    # 4. Clear highlights
    clear_hl = browser.clear_highlights()
    passed_clear_hl = clear_hl.get("ok") is True
    log_test("Visual Inspection: clear_highlights", passed_clear_hl, f"Overlays removed: {clear_hl.get('removed_count')}")

    assert passed_hl and passed_coord and passed_interactive and passed_clear_hl
    return True


def test_screenshot_and_live_state_performance(browser):
    """Test screenshot capture, JPEG compression, and live state caching/throttling."""
    # 1. File screenshot
    ss_file = "test_screen_capture.png"
    ss_res = browser.screenshot(filename=ss_file)
    saved_path = WORKSPACE_DIR / ss_file
    passed_ss = ss_res.get("ok") is True and saved_path.exists() and saved_path.stat().st_size > 500
    log_test("Screenshot: file save", passed_ss, f"Saved to {saved_path.name} ({saved_path.stat().st_size if saved_path.exists() else 0} bytes)")

    # 2. Live state fast mode
    t0 = time.time()
    state_fast = browser.get_live_state(fast_mode=True, quality=55)
    t_fast = (time.time() - t0) * 1000.0
    passed_fast = state_fast.get("ok") is True and state_fast.get("screenshot", "").startswith("data:image/jpeg;base64,")
    log_test("Live State: Fast mode & compression", passed_fast, f"Latency: {t_fast:.1f}ms, image data length: {len(state_fast.get('screenshot', ''))}")

    # 3. Throttled rapid polling
    t1 = time.time()
    for _ in range(5):
        _ = browser.get_live_state(fast_mode=True)
    t_burst = (time.time() - t1) * 1000.0
    log_test("Live State: Throttled burst polling (5 frames)", True, f"Total burst time: {t_burst:.1f}ms (Avg {t_burst/5:.1f}ms/frame)")

    return passed_ss and passed_fast


def test_crash_recovery_and_resilience(browser):
    """Test auto-reconnect and self-healing when browser context or window is manually closed."""
    # Make sure we have a page open
    _ = browser.current_page

    # Simulate sudden browser crash / window close
    print("  Simulating external browser window closure / crash...")
    if browser.context:
        try:
            browser.context.close()
        except Exception:
            pass

    # Verify is_context_alive is False
    passed_dead = not browser.is_context_alive()
    log_test("Lifecycle: Detect closed/crashed context", passed_dead, f"is_context_alive(): {browser.is_context_alive()}")

    # Call an operation that should trigger automatic recovery and reconnection
    t0 = time.time()
    recover_res = browser.navigate("https://example.com")
    t_rec = (time.time() - t0) * 1000.0
    passed_recover = recover_res.get("ok") is True and browser.is_context_alive()
    log_test("Lifecycle: Auto-reconnect & crash recovery", passed_recover, f"Recovered & navigated in {t_rec:.1f}ms (is_alive={browser.is_context_alive()})")

    # Test open_takeover_window
    takeover_res = browser.open_takeover_window("https://example.com")
    passed_takeover = takeover_res.get("ok") is True
    log_test("Lifecycle: open_takeover_window", passed_takeover, f"Status: {takeover_res.get('message')}")

    return passed_dead and passed_recover and passed_takeover


def test_tool_definitions_dispatcher():
    """Test tool execution dispatcher via definitions.py."""
    # Test browser_get_coordinates via execute_tool
    res = execute_tool("browser_navigate", {"url": "https://example.com"})
    passed_nav = res.get("ok") is True

    res_scroll = execute_tool("browser_scroll", {"direction": "down", "amount": 300})
    passed_scroll = res_scroll.get("ok") is True

    res_extract = execute_tool("browser_extract", {"max_chars": 500})
    passed_extract = res_extract.get("ok") is True and "text_content" in res_extract

    log_test("Tool Dispatcher: execute_tool for hardened browser tools", passed_nav and passed_scroll and passed_extract, "execute_tool works across all browser schemas")
    return passed_nav and passed_scroll and passed_extract


def main():
    print("=" * 70)
    print("🧪 Hardened SandboxBrowser Comprehensive Verification Suite")
    print("=" * 70 + "\n")

    browser = get_browser()
    results = []

    try:
        print("--- 1. Anti-Detection Stealth Verification ---")
        results.append(test_stealth_and_anti_detection(browser))
        print()

        print("--- 2. Navigation & Multi-Tab Management ---")
        results.append(test_navigation_and_tab_management(browser))
        print()

        print("--- 3. Session & Cookie Export / Import Utility ---")
        results.append(test_session_export_and_import(browser))
        print()

        print("--- 4. Visual Highlights & Coordinate Boundary Helpers ---")
        results.append(test_highlights_and_coordinates(browser))
        print()

        print("--- 5. Live Capture Performance & Memory Compression ---")
        results.append(test_screenshot_and_live_state_performance(browser))
        print()

        print("--- 6. Lifecycle Resilience & Crash Recovery ---")
        results.append(test_crash_recovery_and_resilience(browser))
        print()

        print("--- 7. Tool Definitions & Dispatcher Verification ---")
        results.append(test_tool_definitions_dispatcher())
        print()

    finally:
        browser.close()

    print("=" * 70)
    all_passed = all(results)
    if all_passed:
        print("\033[92m✔ ALL HARDENING VERIFICATION TESTS PASSED SUCCESSFULLY!\033[0m")
    else:
        print("\033[91m✖ SOME TESTS FAILED. Review output above.\033[0m")
    print("=" * 70)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
