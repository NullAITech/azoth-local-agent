"""Sandboxed Always-Headed Interactive Browser Engine for a-bot.

Guarantees & Hardened Capabilities:
- ALWAYS HEADED: Never runs headless; operates as a real visible Chromium window in the sandbox.
- Resilient Lifecycle: Automatic reconnection on window close, graceful crash recovery, profile lock self-healing.
- Anti-Detection Stealth: Complete navigator.webdriver masking, mock Chrome plugins/runtime, authentic Linux User-Agent.
- Session & Cookie Management: Backup, export, import, and restore of authenticated account sessions.
- High-Performance Capture: Throttled, memory-efficient JPEG screenshot compression with caching.
- Visual Inspection: DOM element-level bounding box highlights and coordinate boundary calculations.
- Multi-Tab & Multi-Input: Full coordinate clicks, typing, smooth scrolling, tab management, and CAPTCHA detection.
"""

from __future__ import annotations

import atexit
import base64
import concurrent.futures
import json
import math
import os
import random
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = ROOT / "sandbox"
BROWSER_PROFILE_DIR = SANDBOX_DIR / "browser_profile"
WORKSPACE_DIR = SANDBOX_DIR / "workspace"
DOWNLOADS_DIR = SANDBOX_DIR / "downloads"

# Default Authentic Linux User Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

# Injected Anti-Detection Stealth Initialization Script
STEALTH_INIT_SCRIPT = """
(() => {
  // 1. Mask navigator.webdriver
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined,
      configurable: true
    });
    delete Object.getPrototypeOf(navigator).webdriver;
  } catch (e) {}

  // 2. Mock authentic Chrome object and runtime
  try {
    window.chrome = {
      app: {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
      },
      runtime: {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
        RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
      },
      loadTimes: function() {},
      csi: function() {}
    };
  } catch (e) {}

  // 3. Mock authentic languages
  try {
    Object.defineProperty(navigator, 'languages', {
      get: () => ['en-US', 'en'],
      configurable: true
    });
    Object.defineProperty(navigator, 'language', {
      get: () => 'en-US',
      configurable: true
    });
  } catch (e) {}

  // 4. Mock authentic plugins array
  try {
    const mockPlugins = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
    ];
    Object.defineProperty(navigator, 'plugins', {
      get: () => mockPlugins,
      configurable: true
    });
  } catch (e) {}

  // 5. Mock permissions query
  try {
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
      parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
  } catch (e) {}

  // 6. Hardware specs
  try {
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });
  } catch (e) {}
})();
"""


def get_chrome_path() -> Optional[str]:
    """Find system Google Chrome or Chromium executable."""
    candidates = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/opt/google/chrome/chrome",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def get_user_agent() -> str:
    """Return standard realistic User Agent."""
    return DEFAULT_USER_AGENT


def _cleanup_profile_locks(profile_dir: Path) -> None:
    """Remove stale Chromium profile lock files and symlinks."""
    if not profile_dir.exists():
        return
    lock_patterns = ["SingletonLock", "SingletonCookie", "SingletonSocket", "LOCK", "LOCK.old"]
    for name in lock_patterns:
        p = profile_dir / name
        try:
            if p.is_symlink() or p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass


def _kill_lingering_chrome_for_profile(profile_dir: Path) -> None:
    """Kill lingering Chrome processes associated specifically with the sandbox browser profile."""
    try:
        profile_str = str(profile_dir.resolve())
        subprocess.run(
            ["pkill", "-9", "-f", f"user-data-dir={profile_str}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


class SandboxBrowser:
    """Manages an always-headed, hardened Playwright browser with persistent profile and crash recovery."""

    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.active_page_index: int = 0
        self._lock = threading.RLock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-worker")
        self._worker_thread: Optional[threading.Thread] = None

        # Performance & screenshot caching
        self._last_screenshot_b64: Optional[str] = None
        self._last_screenshot_time: float = 0.0
        self._screenshot_throttle_sec: float = 0.15

        # Directory preparation
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

        # Register clean exit handler
        atexit.register(self.close)

    def is_context_alive(self) -> bool:
        """Check if browser context and playwright instance are alive."""
        if self.context is None or self.playwright is None:
            return False
        try:
            pages = self.context.pages
            if not pages:
                return False
            # Lightweight probe
            _ = pages[0].url
            return True
        except Exception:
            return False

    def _close_internal(self) -> None:
        """Internal teardown without throwing."""
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

    def _ensure_browser(self, force_restart: bool = False) -> Page:
        """Ensure the browser is running (Always Headed) with crash self-healing."""
        with self._lock:
            if force_restart or not self.is_context_alive():
                self._close_internal()
                _kill_lingering_chrome_for_profile(BROWSER_PROFILE_DIR)
                _cleanup_profile_locks(BROWSER_PROFILE_DIR)

                if self.playwright is None:
                    self.playwright = sync_playwright().start()

                chrome_path = get_chrome_path()
                launch_args = [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=IsolateOrigins,site-per-process,TranslateUI,OptimizationHints",
                    "--window-size=1280,800",
                    "--window-position=50,50",
                    "--lang=en-US,en",
                    "--force-color-profile=srgb",
                ]

                kwargs: dict[str, Any] = {
                    "user_data_dir": str(BROWSER_PROFILE_DIR),
                    "headless": False,  # ALWAYS headed
                    "args": launch_args,
                    "ignore_default_args": ["--enable-automation"],
                    "viewport": {"width": 1280, "height": 800},
                    "user_agent": get_user_agent(),
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                    "accept_downloads": True,
                    "color_scheme": "light",
                }
                if chrome_path:
                    kwargs["executable_path"] = chrome_path

                # Launch with resilient retry loop
                last_exc = None
                for attempt in range(1, 4):
                    try:
                        self.context = self.playwright.chromium.launch_persistent_context(**kwargs)
                        break
                    except Exception as exc:
                        last_exc = exc
                        time.sleep(0.4 * attempt)
                        _kill_lingering_chrome_for_profile(BROWSER_PROFILE_DIR)
                        _cleanup_profile_locks(BROWSER_PROFILE_DIR)
                        try:
                            if self.playwright:
                                self.playwright.stop()
                        except Exception:
                            pass
                        self.playwright = sync_playwright().start()

                if self.context is None:
                    raise last_exc or RuntimeError("Failed to launch sandboxed browser context.")

                # Inject stealth hooks into all pages and frames
                self.context.add_init_script(STEALTH_INIT_SCRIPT)

                if not self.context.pages:
                    self.context.new_page()
                self.active_page_index = 0

            pages = self.context.pages
            if not pages:
                page = self.context.new_page()
                self.active_page_index = 0
                return page

            if self.active_page_index >= len(pages):
                self.active_page_index = max(0, len(pages) - 1)

            return pages[self.active_page_index]

    @property
    def current_page(self) -> Page:
        """Return the current active Page object."""
        if threading.current_thread() == self._worker_thread:
            return self._ensure_browser()
        future = self._executor.submit(self._ensure_browser)
        return future.result()

    def with_page(self, fn: Callable[[Page], Any]) -> Any:
        """Run custom actions with the active Page object on the dedicated browser thread."""
        return self._with_recovery(fn)

    def _with_recovery(self, fn: Callable[[Page], Any]) -> Any:
        """Execute a page function on the dedicated browser worker thread with automatic 1-time crash recovery."""
        if threading.current_thread() == self._worker_thread:
            return self._run_recovery_internal(fn)
        future = self._executor.submit(self._run_recovery_internal, fn)
        return future.result()

    def _run_recovery_internal(self, fn: Callable[[Page], Any]) -> Any:
        self._worker_thread = threading.current_thread()
        with self._lock:
            try:
                page = self._ensure_browser()
                return fn(page)
            except Exception as e:
                err_msg = str(e).lower()
                # Check for closed page / context / target or broken pipe or thread error
                if any(kw in err_msg for kw in ["closed", "connection", "target", "crash", "destroyed", "navigating", "thread", "greenlet", "loop"]):
                    page = self._ensure_browser(force_restart=True)
                    return fn(page)
                raise e

    def open_takeover_window(self, url: str = "https://google.com") -> dict[str, Any]:
        """Launch or focus the visible Sandboxed Chrome window."""
        def _action(page: Page) -> dict[str, Any]:
            if url and page.url != url and page.url == "about:blank":
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
            page.bring_to_front()
            return {
                "ok": True,
                "url": page.url,
                "title": page.title(),
                "message": f"Browser window active at {page.url}",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_tabs(self) -> list[dict[str, Any]]:
        """List all open browser tabs."""
        try:
            self._ensure_browser()
            tabs = []
            if not self.context:
                return tabs

            for i, p in enumerate(self.context.pages):
                try:
                    title = p.title() or "Untitled Tab"
                    url = p.url or "about:blank"
                except Exception:
                    title = "Tab"
                    url = "about:blank"
                tabs.append({
                    "index": i,
                    "title": title,
                    "url": url,
                    "active": i == self.active_page_index,
                })
            return tabs
        except Exception:
            return []

    def new_tab(self, url: str = "https://google.com") -> dict[str, Any]:
        """Open a new browser tab."""
        def _action(page: Page) -> dict[str, Any]:
            target_url = url
            if (
                not target_url.startswith("http://")
                and not target_url.startswith("https://")
                and not target_url.startswith("file://")
                and target_url != "about:blank"
            ):
                target_url = "https://" + target_url

            assert self.context is not None
            new_p = self.context.new_page()
            self.active_page_index = len(self.context.pages) - 1
            if target_url and target_url != "about:blank":
                try:
                    new_p.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass

            return {"ok": True, "active_tab": self.active_page_index, "tabs": self.list_tabs()}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def switch_tab(self, index: int) -> dict[str, Any]:
        """Switch active tab to given index."""
        def _action(page: Page) -> dict[str, Any]:
            assert self.context is not None
            if not self.context.pages:
                return {"ok": False, "error": "No tabs open"}

            if 0 <= index < len(self.context.pages):
                self.active_page_index = index
                p = self.context.pages[index]
                try:
                    p.bring_to_front()
                except Exception:
                    pass
                return {"ok": True, "active_tab": index, "tabs": self.list_tabs()}
            return {"ok": False, "error": f"Invalid tab index {index}"}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close_tab(self, index: int) -> dict[str, Any]:
        """Close tab at index."""
        def _action(page: Page) -> dict[str, Any]:
            assert self.context is not None
            if not self.context.pages:
                return {"ok": False, "error": "No tabs open"}

            if 0 <= index < len(self.context.pages):
                p = self.context.pages[index]
                try:
                    p.close()
                except Exception:
                    pass
                if not self.context.pages:
                    self.context.new_page()
                self.active_page_index = max(0, min(self.active_page_index, len(self.context.pages) - 1))
                return {"ok": True, "tabs": self.list_tabs(), "active_tab": self.active_page_index}
            return {"ok": False, "error": "Invalid tab index"}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> dict[str, Any]:
        """Direct mouse click at pixel coordinates (x, y)."""
        def _action(page: Page) -> dict[str, Any]:
            page.mouse.click(x, y, button=button, click_count=click_count)
            page.wait_for_timeout(250)
            return {"ok": True, "x": x, "y": y, "button": button, "click_count": click_count}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def mouse_move(self, x: int, y: int) -> dict[str, Any]:
        """Move mouse cursor to (x, y)."""
        def _action(page: Page) -> dict[str, Any]:
            page.mouse.move(x, y)
            return {"ok": True, "x": x, "y": y}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def mouse_wheel(self, delta_x: int = 0, delta_y: int = 200) -> dict[str, Any]:
        """Mouse wheel scroll."""
        def _action(page: Page) -> dict[str, Any]:
            page.mouse.wheel(delta_x, delta_y)
            page.wait_for_timeout(150)
            return {"ok": True, "delta_x": delta_x, "delta_y": delta_y}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def keyboard_type(self, text: str, delay: int = 20) -> dict[str, Any]:
        """Type characters from keyboard with natural delay."""
        def _action(page: Page) -> dict[str, Any]:
            page.keyboard.type(text, delay=delay)
            page.wait_for_timeout(150)
            return {"ok": True, "text": text}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def keyboard_press(self, key: str) -> dict[str, Any]:
        """Press special key (Enter, Backspace, Tab, Escape, ArrowDown, etc.)."""
        def _action(page: Page) -> dict[str, Any]:
            key_map = {
                "Enter": "Enter",
                "Backspace": "Backspace",
                "Tab": "Tab",
                "Escape": "Escape",
                "ArrowDown": "ArrowDown",
                "ArrowUp": "ArrowUp",
                "ArrowLeft": "ArrowLeft",
                "ArrowRight": "ArrowRight",
                "Space": " ",
            }
            mapped_key = key_map.get(key, key)
            page.keyboard.press(mapped_key)
            page.wait_for_timeout(200)
            return {"ok": True, "key": key}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def detect_verification(self) -> dict[str, Any]:
        """Detect CAPTCHA, Cloudflare challenge, or 2FA."""
        try:
            page = self.current_page
            html = page.content().lower()
            title = page.title().lower()

            patterns = [
                ("cloudflare", r"cf-turnstile|cf-challenge|just a moment\.\.\.|ray id:"),
                ("recaptcha", r"g-recaptcha|google\.com/recaptcha|recaptcha-anchor"),
                ("hcaptcha", r"hcaptcha\.com|h-captcha"),
                ("arkose", r"arkoselabs|funcaptcha"),
                ("bot_detection", r"verify you are human|unusual traffic|prove you're human|access denied"),
                ("two_factor", r"two-factor|verification code|authenticator app|2fa|enter the code"),
            ]

            for vtype, regex in patterns:
                if re.search(regex, html) or re.search(regex, title):
                    return {
                        "detected": True,
                        "type": vtype,
                        "title": page.title(),
                        "url": page.url,
                        "message": f"Verification challenge ({vtype}) detected on {page.url}.",
                    }

            return {"detected": False, "url": page.url, "title": page.title()}
        except Exception:
            return {"detected": False}

    def navigate(self, url: str) -> dict[str, Any]:
        """Navigate active tab to a URL."""
        if (
            not url.startswith("http://")
            and not url.startswith("https://")
            and not url.startswith("file://")
            and url != "about:blank"
        ):
            url = "https://" + url

        def _action(page: Page) -> dict[str, Any]:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else 200
            page.wait_for_timeout(1000)
            title = page.title()
            v_check = self.detect_verification()

            return {
                "ok": True,
                "url": page.url,
                "title": title,
                "status": status,
                "verification": v_check,
                "tabs": self.list_tabs(),
                "summary": f"Navigated to {page.url} ('{title}')",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "url": url}

    def click(self, selector: str) -> dict[str, Any]:
        """Click element by selector or text."""
        def _action(page: Page) -> dict[str, Any]:
            try:
                page.click(selector, timeout=5000)
            except Exception:
                page.get_by_text(selector).first.click(timeout=5000)

            page.wait_for_timeout(600)
            return {
                "ok": True,
                "url": page.url,
                "title": page.title(),
                "summary": f"Clicked '{selector}' on {page.url}",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def type_text(self, selector: str, text: str, press_enter: bool = False) -> dict[str, Any]:
        """Type text into element."""
        def _action(page: Page) -> dict[str, Any]:
            page.fill(selector, text, timeout=5000)
            if press_enter:
                page.press(selector, "Enter")
                page.wait_for_timeout(800)
            return {
                "ok": True,
                "selector": selector,
                "summary": f"Typed into '{selector}'",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def human_move(self, target_x: int, target_y: int, steps: int = 15) -> dict[str, Any]:
        """Move cursor naturally along a curved path with realistic acceleration and deceleration."""
        def _action(page: Page) -> dict[str, Any]:
            start_x = getattr(self, "_last_mouse_x", 300)
            start_y = getattr(self, "_last_mouse_y", 300)

            # Generate control point for cubic bezier curve
            mid_x = (start_x + target_x) / 2 + random.uniform(-35, 35)
            mid_y = (start_y + target_y) / 2 + random.uniform(-35, 35)

            for i in range(1, steps + 1):
                t = i / float(steps)
                bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * mid_x + t ** 2 * target_x
                by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * mid_y + t ** 2 * target_y
                page.mouse.move(bx, by)
                time.sleep(random.uniform(0.008, 0.020))

            self._last_mouse_x = target_x
            self._last_mouse_y = target_y
            return {"ok": True, "x": target_x, "y": target_y}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def human_click(self, selector: str, button: str = "left") -> dict[str, Any]:
        """Move mouse naturally to element, pause realistically, and click."""
        def _action(page: Page) -> dict[str, Any]:
            loc = page.locator(selector).first
            loc.scroll_into_view_if_needed(timeout=5000)
            box = loc.bounding_box()
            if not box:
                loc.click(button=button, timeout=5000)
                return {"ok": True, "selector": selector, "fallback": True}

            # Natural offset inside element
            cx = box["x"] + box["width"] * random.uniform(0.35, 0.65)
            cy = box["y"] + box["height"] * random.uniform(0.35, 0.65)

            self.human_move(int(cx), int(cy))
            time.sleep(random.uniform(0.07, 0.16))

            page.mouse.down(button=button)
            time.sleep(random.uniform(0.04, 0.09))
            page.mouse.up(button=button)
            page.wait_for_timeout(350)
            return {"ok": True, "selector": selector, "x": int(cx), "y": int(cy)}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def human_type(self, selector: str, text: str, press_enter: bool = False, clear_first: bool = True) -> dict[str, Any]:
        """Focus element and type text with human cadence, variable delays, and occasional micro-pauses."""
        def _action(page: Page) -> dict[str, Any]:
            loc = page.locator(selector).first
            loc.scroll_into_view_if_needed(timeout=5000)
            
            box = loc.bounding_box()
            if box:
                cx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                cy = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                page.mouse.click(cx, cy)
            else:
                loc.click()

            time.sleep(random.uniform(0.1, 0.22))

            if clear_first:
                page.keyboard.press("Control+A")
                time.sleep(random.uniform(0.05, 0.1))
                page.keyboard.press("Backspace")
                time.sleep(random.uniform(0.08, 0.18))

            start_t = time.time()
            for ch in text:
                page.keyboard.type(ch)
                if ch in (" ", ".", ",", "-", "_", "@", "!"):
                    time.sleep(random.uniform(0.12, 0.26))
                else:
                    time.sleep(random.uniform(0.035, 0.10))
                
                if random.random() < 0.05:
                    time.sleep(random.uniform(0.15, 0.35))

            if press_enter:
                time.sleep(random.uniform(0.15, 0.35))
                page.keyboard.press("Enter")
                page.wait_for_timeout(800)

            duration_ms = int((time.time() - start_t) * 1000)
            return {"ok": True, "selector": selector, "typed_length": len(text), "duration_ms": duration_ms}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def smart_login(
        self,
        url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        user_selector: Optional[str] = None,
        pass_selector: Optional[str] = None,
        submit_selector: Optional[str] = None,
        wait_sec: int = 4,
    ) -> dict[str, Any]:
        """
        Intelligently automate website login: detects inputs, types with human cadence,
        handles multi-step flows, detects 2FA/CAPTCHA, and automatically exports session cookies.
        """
        def _action(page: Page) -> dict[str, Any]:
            if url and not page.url.startswith(url):
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1500)

            auth_check = self.check_auth()
            if auth_check.get("authenticated"):
                return {
                    "ok": True,
                    "status": "already_authenticated",
                    "url": page.url,
                    "message": "User is already authenticated on this site.",
                    "auth": auth_check,
                }

            user_candidates = [
                user_selector,
                'input[autocomplete="username"]',
                'input[name="username"]',
                'input[name="email"]',
                'input[name="login"]',
                'input[name="identifier"]',
                'input[type="email"]',
                'input[placeholder*="username" i]',
                'input[placeholder*="email" i]',
                'input[placeholder*="phone" i]',
                'input[name="text"]',
                'input[type="text"]',
            ]
            
            user_loc = None
            found_user_sel = None
            if username:
                for sel in filter(None, user_candidates):
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=400):
                            user_loc = loc
                            found_user_sel = sel
                            break
                    except Exception:
                        continue

                if user_loc:
                    self.human_type(found_user_sel, username)
                    page.wait_for_timeout(500)
                else:
                    return {
                        "ok": False,
                        "error": "Could not locate username/email input field.",
                        "url": page.url,
                    }

            pass_candidates = [
                pass_selector,
                'input[type="password"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
                'input[placeholder*="password" i]',
            ]
            
            pass_loc = None
            for sel in filter(None, pass_candidates):
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=400):
                        pass_loc = loc
                        break
                except Exception:
                    continue

            if not pass_loc and username:
                next_candidates = [
                    'button:has-text("Next")',
                    'button:has-text("Continue")',
                    'button:has-text("Sign in")',
                    'button:has-text("Log in")',
                    'button[type="submit"]',
                    'div[role="button"]:has-text("Next")',
                ]
                for n_sel in next_candidates:
                    try:
                        n_loc = page.locator(n_sel).first
                        if n_loc.is_visible(timeout=500):
                            self.human_click(n_sel)
                            page.wait_for_timeout(1800)
                            break
                    except Exception:
                        pass
                else:
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1800)

            found_pass_sel = None
            for sel in filter(None, pass_candidates):
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=1500):
                        found_pass_sel = sel
                        break
                except Exception:
                    continue

            if found_pass_sel and password:
                self.human_type(found_pass_sel, password)
                page.wait_for_timeout(400)
            elif password:
                return {
                    "ok": False,
                    "error": "Could not locate password input field.",
                    "url": page.url,
                }

            submit_candidates = [
                submit_selector,
                'button[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("Sign in")',
                'div[role="button"]:has-text("Log in")',
                'div[role="button"]:has-text("Sign in")',
                'input[type="submit"]',
            ]
            
            submitted = False
            for s_sel in filter(None, submit_candidates):
                try:
                    s_loc = page.locator(s_sel).first
                    if s_loc.is_visible(timeout=500):
                        self.human_click(s_sel)
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                page.keyboard.press("Enter")

            page.wait_for_timeout(wait_sec * 1000)

            verif = self.detect_verification()
            if verif.get("detected"):
                return {
                    "ok": True,
                    "status": "2fa_required",
                    "verification": verif,
                    "url": page.url,
                    "title": page.title(),
                    "message": f"Authentication challenge ({verif.get('type')}) detected. User takeover or 2FA required in Live Browser.",
                }

            post_auth = self.check_auth()
            if post_auth.get("authenticated"):
                self.export_session()
                return {
                    "ok": True,
                    "success": True,
                    "status": "success",
                    "step": "completed",
                    "url": page.url,
                    "title": page.title(),
                    "message": "Login successful! Session and cookies have been saved to browser profile.",
                    "auth": post_auth,
                }

            return {
                "ok": True,
                "success": post_auth.get("authenticated", False),
                "status": "pending_or_unknown",
                "step": "submitted",
                "url": page.url,
                "title": page.title(),
                "message": f"Login submitted. Current page: {page.url}.",
                "auth": post_auth,
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_auth(self, url_or_domain: Optional[str] = None) -> dict[str, Any]:
        """Inspect current page or domain to determine if an active authenticated user session exists."""
        def _action(page: Page) -> dict[str, Any]:
            if url_or_domain and not page.url.startswith(url_or_domain):
                page.goto(url_or_domain, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1000)

            curr_url = page.url.lower()

            auth_indicators = [
                ('[data-testid="SideNav_AccountSwitcher_Button"]', 'X Account Menu'),
                ('[data-testid="AppTabBar_Profile_Link"]', 'X Profile Link'),
                ('[aria-label="Account menu"]', 'Account Menu'),
                ('button[aria-label="Open user account menu"]', 'GitHub Account Menu'),
                ('header summary img.avatar', 'GitHub User Avatar'),
                ('a[aria-label*="Google Account" i]', 'Google Account Avatar'),
                ('button:has-text("Sign Out")', 'Sign Out Button'),
                ('a:has-text("Log Out")', 'Log Out Link'),
                ('a:has-text("Sign Out")', 'Sign Out Link'),
                ('button:has-text("Log out")', 'Log out Button'),
                ('[data-testid="user-profile"]', 'User Profile Widget'),
                ('.user-avatar', 'User Avatar Class'),
            ]

            guest_indicators = [
                ('button:has-text("Sign In")', 'Sign In Button'),
                ('a:has-text("Log In")', 'Log In Link'),
                ('a[href*="/login"]', 'Login Link'),
                ('a[href*="/signin"]', 'Sign-in Link'),
                ('input[type="password"]', 'Password Input Field'),
            ]

            detected_signals = []
            for sel, desc in auth_indicators:
                try:
                    if page.locator(sel).first.is_visible(timeout=200):
                        detected_signals.append(desc)
                except Exception:
                    pass

            detected_guest = []
            for sel, desc in guest_indicators:
                try:
                    if page.locator(sel).first.is_visible(timeout=200):
                        detected_guest.append(desc)
                except Exception:
                    pass

            assert self.context is not None
            cookies = self.context.cookies()
            auth_cookies = [
                c.get("name") for c in cookies
                if any(k in c.get("name", "").lower() for k in ("auth", "session", "token", "login", "ssid", "user"))
            ]

            is_auth = len(detected_signals) > 0 or (len(auth_cookies) >= 2 and len(detected_guest) == 0 and "login" not in curr_url)

            # Detect user handle/name
            detected_user = None
            if is_auth:
                try:
                    detected_user = page.evaluate("""() => {
                        const match = document.body.innerText.match(/@([a-zA-Z0-9_]{2,30})/);
                        if (match) return match[1];
                        const userMeta = document.querySelector('meta[name="user-login"], [data-login], [data-user]');
                        if (userMeta) return userMeta.getAttribute('content') || userMeta.getAttribute('data-login') || userMeta.getAttribute('data-user');
                        const profileLink = document.querySelector('a[href*="/settings/profile"], a[href*="/user/"], a[href*="/profile/"]');
                        if (profileLink && profileLink.innerText.trim() && !profileLink.innerText.toLowerCase().includes('profile')) return profileLink.innerText.trim();
                        return null;
                    }""")
                except Exception:
                    pass

            return {
                "ok": True,
                "authenticated": is_auth,
                "user": detected_user,
                "url": page.url,
                "title": page.title(),
                "auth_signals": detected_signals,
                "guest_signals": detected_guest,
                "auth_cookies_found": len(auth_cookies),
                "summary": f"Authenticated session active ({detected_user or 'user'})" if is_auth else "Not authenticated (guest / login page)",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def fill_form(self, fields: dict[str, str], submit_selector: Optional[str] = None) -> dict[str, Any]:
        """Fill multiple form inputs sequentially with human typing delays."""
        def _action(page: Page) -> dict[str, Any]:
            results = []
            for selector, value in fields.items():
                res = self.human_type(selector, value)
                results.append({"selector": selector, "ok": res.get("ok", False)})
                page.wait_for_timeout(random.randint(150, 400))

            if submit_selector:
                self.human_click(submit_selector)
                page.wait_for_timeout(1000)

            return {"ok": True, "fields_filled": len(results), "details": results}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_takeover(self, url: str = "https://x.com", reason: str = "") -> dict[str, Any]:
        """Alias for open_takeover_window with optional user reason badge."""
        return self.open_takeover_window(url=url)

    def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        """Scroll active webpage up, down, top, or bottom."""
        def _action(page: Page) -> dict[str, Any]:
            dir_lower = direction.lower()
            if dir_lower == "bottom":
                page.evaluate("() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })")
            elif dir_lower == "top":
                page.evaluate("() => window.scrollTo({ top: 0, behavior: 'smooth' })")
            else:
                delta_y = amount if dir_lower == "down" else -amount
                page.mouse.wheel(0, delta_y)
            page.wait_for_timeout(200)
            return {"ok": True, "direction": direction, "amount": amount, "summary": f"Scrolled {direction}"}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def screenshot(self, filename: str = "screenshot.png", full_page: bool = False) -> dict[str, Any]:
        """Save a screenshot of the active browser page into the sandbox workspace."""
        def _action(page: Page) -> dict[str, Any]:
            out_path = Path(filename)
            if not out_path.is_absolute():
                out_path = WORKSPACE_DIR / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path), full_page=full_page, type="png")
            return {
                "ok": True,
                "path": str(out_path),
                "filename": out_path.name,
                "summary": f"Screenshot saved to {out_path.name}",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def wait_for(self, selector_or_text: str, timeout_ms: int = 10000) -> dict[str, Any]:
        """Wait for a selector or text to appear on the active page."""
        def _action(page: Page) -> dict[str, Any]:
            try:
                page.wait_for_selector(selector_or_text, timeout=timeout_ms, state="visible")
            except Exception:
                page.get_by_text(selector_or_text).first.wait_for(timeout=timeout_ms, state="visible")
            return {
                "ok": True,
                "target": selector_or_text,
                "summary": f"Element/text '{selector_or_text}' appeared successfully.",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "target": selector_or_text}

    def evaluate_js(self, script: str) -> dict[str, Any]:
        """Evaluate custom JavaScript in the active page context."""
        def _action(page: Page) -> dict[str, Any]:
            result = page.evaluate(script)
            return {"ok": True, "result": result}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # Visual Highlights & Coordinate Boundary Helpers
    # =========================================================================

    def highlight_element(
        self,
        selector: str,
        duration_ms: int = 2500,
        color: str = "#1a73e8",
        label: Optional[str] = None,
    ) -> dict[str, Any]:
        """Visually highlight an element with a glowing outline and return exact coordinates."""
        def _action(page: Page) -> dict[str, Any]:
            js_payload = """
            (args) => {
                const { selector, durationMs, color, label } = args;
                let el = null;
                try {
                    el = document.querySelector(selector);
                } catch (e) {}

                if (!el) {
                    const all = document.querySelectorAll('button, a, input, [role="button"], span, div, p, h1, h2, h3, label');
                    for (const item of all) {
                        if (item.textContent && item.textContent.trim().toLowerCase().includes(selector.toLowerCase())) {
                            el = item;
                            break;
                        }
                    }
                }

                if (!el) {
                    return { found: false, error: 'Element not found: ' + selector };
                }

                const rect = el.getBoundingClientRect();
                const coords = {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    center_x: Math.round(rect.x + rect.width / 2),
                    center_y: Math.round(rect.y + rect.height / 2),
                    visible: rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden' && window.getComputedStyle(el).display !== 'none'
                };

                const overlayId = '__abot_highlight_' + Date.now();
                const overlay = document.createElement('div');
                overlay.id = overlayId;
                overlay.className = '__abot_highlight_overlay';
                overlay.style.position = 'fixed';
                overlay.style.left = (rect.left - 3) + 'px';
                overlay.style.top = (rect.top - 3) + 'px';
                overlay.style.width = (rect.width + 6) + 'px';
                overlay.style.height = (rect.height + 6) + 'px';
                overlay.style.border = `3px solid ${color || '#1a73e8'}`;
                overlay.style.borderRadius = '8px';
                overlay.style.boxShadow = `0 0 16px ${color || '#1a73e8'}, inset 0 0 8px ${color || '#1a73e8'}44`;
                overlay.style.backgroundColor = `${color || '#1a73e8'}18`;
                overlay.style.pointerEvents = 'none';
                overlay.style.zIndex = '2147483647';
                overlay.style.transition = 'all 0.2s ease-in-out';

                const badgeText = label || selector;
                if (badgeText) {
                    const badge = document.createElement('div');
                    badge.textContent = badgeText;
                    badge.style.position = 'absolute';
                    badge.style.bottom = '100%';
                    badge.style.left = '0';
                    badge.style.marginBottom = '4px';
                    badge.style.backgroundColor = color || '#1a73e8';
                    badge.style.color = '#ffffff';
                    badge.style.fontSize = '11px';
                    badge.style.fontFamily = 'monospace';
                    badge.style.fontWeight = 'bold';
                    badge.style.padding = '2px 8px';
                    badge.style.borderRadius = '4px';
                    badge.style.whiteSpace = 'nowrap';
                    badge.style.boxShadow = '0 2px 6px rgba(0,0,0,0.3)';
                    overlay.appendChild(badge);
                }

                document.body.appendChild(overlay);

                if (durationMs > 0) {
                    setTimeout(() => {
                        if (overlay && overlay.parentNode) {
                            overlay.style.opacity = '0';
                            setTimeout(() => overlay.remove(), 250);
                        }
                    }, durationMs);
                }

                return { found: true, coordinates: coords, overlay_id: overlayId };
            }
            """
            res = page.evaluate(js_payload, {
                "selector": selector,
                "durationMs": duration_ms,
                "color": color,
                "label": label or selector,
            })
            if not res.get("found"):
                return {"ok": False, "error": res.get("error", "Element not found"), "selector": selector}
            return {
                "ok": True,
                "selector": selector,
                "coordinates": res["coordinates"],
                "summary": f"Highlighted '{selector}' at ({res['coordinates']['center_x']}, {res['coordinates']['center_y']})",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def clear_highlights(self) -> dict[str, Any]:
        """Remove all injected visual highlight overlays from the page."""
        def _action(page: Page) -> dict[str, Any]:
            count = page.evaluate("""
            () => {
                const overlays = document.querySelectorAll('.__abot_highlight_overlay');
                overlays.forEach(el => el.remove());
                return overlays.length;
            }
            """)
            return {"ok": True, "removed_count": count, "summary": f"Cleared {count} highlight overlays."}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_element_coordinates(self, selector: str) -> dict[str, Any]:
        """Get precise viewport bounding box coordinates of an element."""
        def _action(page: Page) -> dict[str, Any]:
            js = """
            (selector) => {
                let el = null;
                try {
                    el = document.querySelector(selector);
                } catch (e) {}

                if (!el) {
                    const all = document.querySelectorAll('button, a, input, [role="button"], span, div, p, h1, h2, h3, label');
                    for (const item of all) {
                        if (item.textContent && item.textContent.trim().toLowerCase().includes(selector.toLowerCase())) {
                            el = item;
                            break;
                        }
                    }
                }

                if (!el) return { found: false };

                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const visible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                const in_viewport = rect.bottom >= 0 && rect.right >= 0 && rect.top <= window.innerHeight && rect.left <= window.innerWidth;

                return {
                    found: true,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    center_x: Math.round(rect.x + rect.width / 2),
                    center_y: Math.round(rect.y + rect.height / 2),
                    visible: visible,
                    in_viewport: in_viewport
                };
            }
            """
            res = page.evaluate(js, selector)
            if not res.get("found"):
                return {"ok": False, "error": f"Element '{selector}' not found", "selector": selector}
            return {"ok": True, "selector": selector, **res}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def get_interactive_elements_with_bounds(self, max_elements: int = 50) -> dict[str, Any]:
        """Scan active page and return interactive elements with exact bounding coordinates."""
        def _action(page: Page) -> dict[str, Any]:
            js = """
            (maxElements) => {
                const candidates = document.querySelectorAll('a, button, input, textarea, select, [role="button"], [onclick]');
                const items = [];
                for (const el of candidates) {
                    if (items.length >= maxElements) break;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
                        continue;
                    }

                    let label = el.innerText || el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('title') || el.value || '';
                    label = label.trim().replace(/\\s+/g, ' ').slice(0, 40);

                    const tag = el.tagName.toLowerCase();
                    const elType = el.getAttribute('type') || tag;
                    const elId = el.id || '';
                    const elName = el.getAttribute('name') || '';

                    let selector = tag;
                    if (elId) selector = `#${elId}`;
                    else if (elName) selector = `${tag}[name="${elName}"]`;
                    else if (el.className && typeof el.className === 'string') {
                        const firstClass = el.className.trim().split(' ')[0];
                        if (firstClass) selector = `${tag}.${firstClass}`;
                    }

                    items.append || items.push({
                        tag: tag,
                        type: elType,
                        id: elId,
                        name: elName,
                        label: label,
                        selector: selector,
                        bounds: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            center_x: Math.round(rect.x + rect.width / 2),
                            center_y: Math.round(rect.y + rect.height / 2),
                        }
                    });
                }
                return items;
            }
            """
            elements = page.evaluate(js, max_elements)
            return {
                "ok": True,
                "count": len(elements),
                "url": page.url,
                "elements": elements,
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # Session & Cookie Backup/Export/Restore Utility
    # =========================================================================

    def export_session(self, filepath: Optional[str] = None) -> dict[str, Any]:
        """Export browser cookies, localStorage, and session metadata to a JSON file."""
        def _action(page: Page) -> dict[str, Any]:
            assert self.context is not None
            cookies = self.context.cookies()
            storage = {"localStorage": {}, "sessionStorage": {}}
            origin = None

            try:
                origin = page.evaluate("window.location.origin")
                if origin and not origin.startswith("about:"):
                    storage["localStorage"] = page.evaluate("() => Object.assign({}, window.localStorage)")
                    storage["sessionStorage"] = page.evaluate("() => Object.assign({}, window.sessionStorage)")
            except Exception:
                pass

            target_path = Path(filepath) if filepath else (BROWSER_PROFILE_DIR / "session_export.json")
            if not target_path.is_absolute():
                target_path = WORKSPACE_DIR / target_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            domains = sorted(list({c.get("domain", "") for c in cookies if c.get("domain")}))

            payload = {
                "version": "1.0",
                "exported_at": time.time(),
                "exported_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "url": page.url,
                "origin": origin,
                "user_agent": get_user_agent(),
                "cookies_count": len(cookies),
                "domains": domains,
                "cookies": cookies,
                "storage": storage,
            }

            target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return {
                "ok": True,
                "path": str(target_path),
                "filename": target_path.name,
                "cookies_count": len(cookies),
                "domains": domains,
                "summary": f"Exported {len(cookies)} cookies across {len(domains)} domains to {target_path.name}",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def import_session(self, filepath: Optional[str] = None) -> dict[str, Any]:
        """Import browser cookies and session storage from a JSON backup file."""
        def _action(page: Page) -> dict[str, Any]:
            target_path = Path(filepath) if filepath else (BROWSER_PROFILE_DIR / "session_export.json")
            if not target_path.is_absolute():
                target_path = WORKSPACE_DIR / target_path

            if not target_path.exists():
                return {"ok": False, "error": f"Session file not found: {target_path}"}

            try:
                data = json.loads(target_path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": f"Invalid JSON in session file: {e}"}

            # Support both wrapped format and raw cookie array
            cookies = data.get("cookies", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not isinstance(cookies, list):
                return {"ok": False, "error": "Invalid cookie format in session file"}

            assert self.context is not None
            if cookies:
                # Sanitize cookies for Playwright
                valid_cookies = []
                for c in cookies:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        sanitized = {
                            "name": str(c["name"]),
                            "value": str(c["value"]),
                        }
                        if "domain" in c and c["domain"]:
                            sanitized["domain"] = c["domain"]
                        if "path" in c and c["path"]:
                            sanitized["path"] = c["path"]
                        if "expires" in c and isinstance(c["expires"], (int, float)) and c["expires"] > 0:
                            sanitized["expires"] = float(c["expires"])
                        if "httpOnly" in c:
                            sanitized["httpOnly"] = bool(c["httpOnly"])
                        if "secure" in c:
                            sanitized["secure"] = bool(c["secure"])
                        if "sameSite" in c and c["sameSite"] in ("Strict", "Lax", "None"):
                            sanitized["sameSite"] = c["sameSite"]
                        valid_cookies.append(sanitized)

                if valid_cookies:
                    self.context.add_cookies(valid_cookies)

            # Restore localStorage if present and on matching origin
            storage = data.get("storage", {}) if isinstance(data, dict) else {}
            origin = data.get("origin") if isinstance(data, dict) else None
            restored_storage = False

            if storage.get("localStorage") and origin and not origin.startswith("about:"):
                try:
                    curr_origin = page.evaluate("window.location.origin")
                    if curr_origin == origin:
                        page.evaluate("""
                        (storageData) => {
                            for (const [k, v] of Object.entries(storageData)) {
                                window.localStorage.setItem(k, v);
                            }
                        }
                        """, storage["localStorage"])
                        restored_storage = True
                except Exception:
                    pass

            domains = sorted(list({c.get("domain", "") for c in cookies if isinstance(c, dict) and c.get("domain")}))
            return {
                "ok": True,
                "path": str(target_path),
                "cookies_imported": len(cookies),
                "domains": domains,
                "storage_restored": restored_storage,
                "summary": f"Imported {len(cookies)} cookies across {len(domains)} domains.",
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def export_cookies(self, filepath: Optional[str] = None) -> dict[str, Any]:
        """Convenience alias for export_session."""
        return self.export_session(filepath=filepath)

    def import_cookies(self, filepath: str) -> dict[str, Any]:
        """Convenience alias for import_session."""
        return self.import_session(filepath=filepath)

    def clear_session(self, clear_cookies: bool = True, clear_storage: bool = True) -> dict[str, Any]:
        """Clear all active browser cookies and origin storage."""
        def _action(page: Page) -> dict[str, Any]:
            assert self.context is not None
            if clear_cookies:
                self.context.clear_cookies()
            if clear_storage:
                try:
                    page.evaluate("() => { window.localStorage.clear(); window.sessionStorage.clear(); }")
                except Exception:
                    pass
            return {"ok": True, "summary": "Browser session cleared successfully."}

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # Content Extraction & Optimized Live State Capture
    # =========================================================================

    def extract_content(self, max_chars: int = 8000) -> dict[str, Any]:
        """Extract readable text and interactive inputs from active webpage."""
        def _action(page: Page) -> dict[str, Any]:
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            for tag in soup(["script", "style", "svg", "noscript", "meta", "link"]):
                tag.decompose()

            inputs = []
            for inp in soup.find_all(["input", "textarea", "button", "select", "a"])[:40]:
                inp_type = inp.get("type", inp.name)
                inp_id = inp.get("id", "")
                inp_name = inp.get("name", "")
                inp_placeholder = inp.get("placeholder", "")
                inp_text = inp.get_text(strip=True)[:35]
                inp_href = inp.get("href", "")[:40] if inp.name == "a" else ""
                label = inp_placeholder or inp_text or inp_name or inp_id or inp_href or inp_type
                inputs.append(f"[{inp.name}:{inp_type}] {label} (id='{inp_id}', name='{inp_name}')")

            text = soup.get_text(separator=" ", strip=True)
            text_clean = " ".join(text.split())
            if len(text_clean) > max_chars:
                text_clean = text_clean[:max_chars] + "... [truncated]"

            v_check = self.detect_verification()
            return {
                "ok": True,
                "url": page.url,
                "title": page.title(),
                "text_content": text_clean,
                "interactive_elements": inputs,
                "verification": v_check,
                "tabs": self.list_tabs(),
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_live_state(
        self,
        fast_mode: bool = False,
        include_content: bool = True,
        quality: int = 60,
    ) -> dict[str, Any]:
        """Get live screenshot data URI, tabs, URL, and verification status with compression & throttling."""
        def _action(page: Page) -> dict[str, Any]:
            now = time.time()
            b64_img = self._last_screenshot_b64

            # Throttled screenshot capture
            if not b64_img or (now - self._last_screenshot_time) >= self._screenshot_throttle_sec:
                try:
                    screenshot_bytes = page.screenshot(
                        type="jpeg",
                        quality=quality,
                        full_page=False,
                        animations="disabled",
                        timeout=3000,
                    )
                    b64_img = f"data:image/jpeg;base64,{base64.b64encode(screenshot_bytes).decode('utf-8')}"
                    self._last_screenshot_b64 = b64_img
                    self._last_screenshot_time = now
                except Exception:
                    if not b64_img:
                        b64_img = ""

            interactive_elements = []
            if include_content and not fast_mode:
                try:
                    ext = self.extract_content(max_chars=2500)
                    interactive_elements = ext.get("interactive_elements", [])
                except Exception:
                    pass

            v_check = self.detect_verification() if not fast_mode else {"detected": False}

            return {
                "ok": True,
                "url": page.url,
                "title": page.title(),
                "screenshot": b64_img,
                "tabs": self.list_tabs(),
                "active_tab": self.active_page_index,
                "verification": v_check,
                "interactive_elements": interactive_elements,
            }

        try:
            return self._with_recovery(_action)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self) -> None:
        """Clean shutdown of context and Playwright instance."""
        try:
            if threading.current_thread() == self._worker_thread:
                self._close_internal()
            else:
                future = self._executor.submit(self._close_internal)
                future.result(timeout=5)
        except Exception:
            self._close_internal()
        finally:
            _cleanup_profile_locks(BROWSER_PROFILE_DIR)


_browser_instance: Optional[SandboxBrowser] = None


def get_browser() -> SandboxBrowser:
    """Return the global singleton SandboxBrowser instance."""
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = SandboxBrowser()
    return _browser_instance
