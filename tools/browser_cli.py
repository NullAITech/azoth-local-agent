#!/usr/bin/env python3
"""
aZoth Browser CLI Bridge
Enables agents and scripts running inside the Linux Guest OS or host terminal
to control the persistent sandboxed browser, navigate, extract, click, type, and log in.
"""

import sys
import os
import json
import urllib.request
import urllib.parse
from pathlib import Path

# Ensure project root is in sys.path when running on the host
script_dir = Path(__file__).resolve().parent
for candidate in [script_dir, script_dir.parent, script_dir.parent.parent]:
    if (candidate / "tools" / "browser.py").exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

_WORKING_HOST = None


def get_candidate_hosts() -> list[str]:
    """Retrieve candidate API endpoints for host and container environments."""
    hosts = []
    if os.environ.get("AZOTH_API_URL"):
        hosts.append(os.environ["AZOTH_API_URL"].rstrip("/"))

    hosts.extend([
        "http://127.0.0.1:8790",
        "http://192.168.122.1:8790",
        "http://100.125.220.102:8790",
        "http://10.88.0.1:8790",
        "http://172.17.0.1:8790",
        "http://host.containers.internal:8790",
        "http://host.docker.internal:8790",
    ])

    try:
        with open("/proc/net/route") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    gw_hex = fields[2]
                    gw_ip = ".".join(str(int(gw_hex[i:i+2], 16)) for i in (6, 4, 2, 0))
                    gw_url = f"http://{gw_ip}:8790"
                    if gw_url not in hosts:
                        hosts.insert(1, gw_url)
                    break
    except Exception:
        pass
    return hosts


def call_api(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Attempt calling the aZoth API across candidate gateway hosts."""
    global _WORKING_HOST
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}

    candidate_hosts = [_WORKING_HOST] if _WORKING_HOST else get_candidate_hosts()
    for host in candidate_hosts:
        if not host:
            continue
        url = f"{host}{endpoint}"
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    _WORKING_HOST = host
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
    return None


def call_direct_browser(action_name: str, **kwargs) -> dict:
    """Fallback to direct Python browser instance if running on host."""
    try:
        from tools.browser import get_browser
        browser = get_browser()
        fn = getattr(browser, action_name, None)
        if callable(fn):
            return fn(**kwargs)
        return {"ok": False, "error": f"Unknown browser action '{action_name}'"}
    except Exception as e:
        return {"ok": False, "error": f"Direct browser call failed: {e}"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("""⚡ aZoth Browser CLI — Real-User Automation Bridge
Usage:
  azoth-browser navigate <url>
  azoth-browser extract [max_chars]
  azoth-browser screenshot [filename]
  azoth-browser click <selector>
  azoth-browser type <selector> <text> [--enter]
  azoth-browser status
  azoth-browser check-auth [url]
  azoth-browser login <url> <username> <password>
  azoth-browser export-cookies [filename]
  azoth-browser takeover [url] [reason]
""")
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "navigate":
        if len(sys.argv) < 3:
            print("Error: URL required. Usage: azoth-browser navigate <url>")
            sys.exit(1)
        target_url = sys.argv[2]
        res = call_api("/api/browser/input", "POST", {"type": "navigate", "url": target_url})
        if res is None:
            res = call_direct_browser("navigate", url=target_url)
        print(json.dumps(res, indent=2))

    elif cmd == "extract":
        max_c = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
        res = call_api("/api/browser/input", "POST", {"type": "extract", "max_chars": max_c})
        if res is None:
            res = call_direct_browser("extract_content", max_chars=max_c)
        print(json.dumps(res, indent=2))

    elif cmd == "screenshot":
        filename = sys.argv[2] if len(sys.argv) > 2 else "screenshot.png"
        res = call_direct_browser("screenshot", filename=filename)
        print(json.dumps(res, indent=2))

    elif cmd == "click":
        if len(sys.argv) < 3:
            print("Error: Selector required. Usage: azoth-browser click <selector>")
            sys.exit(1)
        selector = sys.argv[2]
        res = call_api("/api/browser/human_click", "POST", {"selector": selector})
        if res is None:
            res = call_direct_browser("human_click", selector=selector)
        if not res or not res.get("ok"):
            res = call_direct_browser("click", selector=selector)
        print(json.dumps(res, indent=2))

    elif cmd == "type":
        if len(sys.argv) < 4:
            print("Error: Selector and text required. Usage: azoth-browser type <selector> <text> [--enter]")
            sys.exit(1)
        selector = sys.argv[2]
        text = sys.argv[3]
        press_enter = "--enter" in sys.argv
        res = call_api("/api/browser/human_type", "POST", {"selector": selector, "text": text, "press_enter": press_enter})
        if res is None:
            res = call_direct_browser("human_type", selector=selector, text=text, press_enter=press_enter)
        if not res or not res.get("ok"):
            res = call_direct_browser("type_text", selector=selector, text=text, press_enter=press_enter)
        print(json.dumps(res, indent=2))

    elif cmd == "status":
        res = call_api("/api/browser/state", "GET")
        if res is None:
            res = call_direct_browser("get_live_state")
        print(json.dumps(res, indent=2))

    elif cmd == "check-auth":
        url = sys.argv[2] if len(sys.argv) > 2 else None
        res = call_api("/api/browser/check_auth", "POST", {"url": url} if url else None)
        if res is None:
            res = call_direct_browser("check_auth", url_or_domain=url)
        print(json.dumps(res, indent=2))

    elif cmd == "login":
        if len(sys.argv) < 5:
            print("Error: URL, username, and password required. Usage: azoth-browser login <url> <user> <pass>")
            sys.exit(1)
        url, username, password = sys.argv[2], sys.argv[3], sys.argv[4]
        res = call_api("/api/browser/login", "POST", {"url": url, "username": username, "password": password})
        if res is None:
            res = call_direct_browser("smart_login", url=url, username=username, password=password)
        print(json.dumps(res, indent=2))

    elif cmd in ("export-cookies", "cookies-export"):
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        res = call_api("/api/browser/session/export", "POST", {"filepath": filename} if filename else None)
        if res is None:
            res = call_direct_browser("export_session", filepath=filename)
        print(json.dumps(res, indent=2))

    elif cmd == "takeover":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://google.com"
        res = call_api("/api/browser/takeover", "POST", {"url": url, "reason": "CLI takeover request"})
        if res is None:
            res = call_direct_browser("open_takeover", url=url, reason="CLI takeover request")
        print(json.dumps(res, indent=2))

    else:
        print(f"Unknown command '{cmd}'. Run 'azoth-browser --help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
