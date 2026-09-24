"""Tool definitions and execution dispatcher for a-bot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .browser import get_browser
from .code_runner import run_python
from .deep_search import deep_search
from .duckyscript import run_duckyscript
from .search import fetch_page, search_web
from .workspace import list_files, read_file, run_shell, write_file
from .x_intelligence import draft_x_thread, inspect_x_post_browser, scout_x_trends, search_x
from .vm_manager import guest_os

ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = ROOT / "MEMORY.md"


def save_memory(note: str) -> dict[str, Any]:
    """Append a lasting preference or note to MEMORY.md."""
    try:
        with MEMORY_PATH.open("a", encoding="utf-8") as f:
            f.write(f"\n- {note.strip()}")
        return {"ok": True, "note": note, "summary": f"Saved note to {MEMORY_PATH.name}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "duckyscript",
            "description": "Execute a DuckyScript payload (DELAY, RANDOM_DELAY, WAIT_FOR, SCREENSHOT, REPLAY, VAR, STRING, ENTER, CTRL+T, CTRL+V, CTRL+ENTER, CLICK, NAVIGATE, SCROLL) against the sandboxed browser or desktop for human-like automation with zero bot detection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "Multi-line DuckyScript payload to execute."},
                    "target": {"type": "string", "enum": ["browser", "os"], "description": "Target environment: 'browser' (Sandboxed Chrome) or 'os' (native desktop). Default is 'browser'."},
                    "vars": {"type": "object", "description": "Optional variable overrides dictionary (e.g. {'SEARCH_TERM': 'plumbing', 'POST_TEXT': 'Hello'})."},
                },
                "required": ["script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate to a URL in the persistent sandboxed Chrome browser (authenticated with your logged-in accounts).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The destination URL or domain."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element, link, or button in the sandboxed browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector or button/link text to click."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into an input field or textarea in the sandboxed browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input element."},
                    "text": {"type": "string", "description": "Text to fill into the element."},
                    "press_enter": {"type": "boolean", "description": "Whether to press Enter after typing."},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_human_click",
            "description": "Click an element naturally using a curved mouse path and humanized micro-delays to avoid bot detection heuristics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector or text of element/button to click."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_human_type",
            "description": "Type text into an input or textarea with authentic human cadence, random pauses, and natural keystroke timing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input element."},
                    "text": {"type": "string", "description": "Text to type with human cadence."},
                    "press_enter": {"type": "boolean", "description": "Whether to press Enter after typing (default False)."},
                    "clear_first": {"type": "boolean", "description": "Whether to clear existing field content first (default True)."},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_login",
            "description": "Log into a website like a real human: discovers login fields, types credentials with human cadence, handles multi-step login flows (Next -> Password), detects 2FA/CAPTCHA challenges, and automatically saves session cookies for permanent reuse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Login page URL."},
                    "username": {"type": "string", "description": "Account username, handle, or email."},
                    "password": {"type": "string", "description": "Account password."},
                    "user_selector": {"type": "string", "description": "Optional CSS selector override for username field."},
                    "pass_selector": {"type": "string", "description": "Optional CSS selector override for password field."},
                    "submit_selector": {"type": "string", "description": "Optional CSS selector override for submit button."},
                },
                "required": ["username", "password"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check_auth",
            "description": "Check if an active authenticated user session exists on the current page or domain (evaluates profile indicators, account menus, and auth cookies).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Optional URL or domain to navigate to and inspect."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill_form",
            "description": "Fill multiple form fields sequentially with human typing delays, optionally clicking submit afterwards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {"type": "object", "description": "Key-value dictionary mapping CSS selectors or field names to values."},
                    "submit_selector": {"type": "string", "description": "Optional submit button selector to click after filling."},
                },
                "required": ["fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_takeover",
            "description": "Request human takeover for 2FA, OTP, CAPTCHA, or verification in the visible Chrome sandbox browser window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the page requiring verification or takeover."},
                    "reason": {"type": "string", "description": "Reason for takeover (e.g. 'Complete SMS 2FA code on X')."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the active webpage up or down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["down", "up"], "description": "Scroll direction (down or up)."},
                    "amount": {"type": "integer", "description": "Pixels to scroll (default 500)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_extract",
            "description": "Extract readable text content and interactive inputs from the active sandboxed browser page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_chars": {"type": "integer", "description": "Maximum characters to extract (default 8000)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Capture a screenshot of the active browser page and save it to the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename for screenshot (e.g. page.png)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a shell command inside the sandbox workspace (azoth-local-agent/sandbox/workspace/).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash shell command to execute."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside sandbox workspace."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file inside the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside sandbox workspace."},
                    "content": {"type": "string", "description": "Text content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Subdirectory to list (default '.')."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web using DuckDuckGo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "Fast HTTP fetch of a public webpage (no JavaScript).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Webpage URL to fetch."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save a lasting user preference, fact, or instruction to MEMORY.md.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "One or two sentence note to remember."},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_session_export",
            "description": "Export current browser cookies and session storage into a JSON backup file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Optional destination filepath (default is sandbox/browser_profile/session_export.json)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_session_import",
            "description": "Import cookies and session storage from a JSON backup file to restore login state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to session JSON backup file."},
                },
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_highlight",
            "description": "Visually highlight a DOM element on the page with a glowing outline and label, returning its bounding coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector or text of element to highlight."},
                    "duration_ms": {"type": "integer", "description": "Duration in ms to keep highlight visible (default 2500)."},
                    "color": {"type": "string", "description": "Highlight color hex or rgb (default '#1a73e8')."},
                    "label": {"type": "string", "description": "Optional text badge to display over the element."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_coordinates",
            "description": "Get exact viewport pixel coordinates (center_x, center_y, width, height) of an element for clicking or dragging.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector or text of element."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_list_interactive",
            "description": "Scan and list all visible interactive elements (buttons, inputs, links) with their exact bounding coordinates and selectors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_elements": {"type": "integer", "description": "Maximum elements to return (default 50)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait_for",
            "description": "Wait for an element or text to appear on the active webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector_or_text": {"type": "string", "description": "CSS selector or text to wait for."},
                    "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds (default 10000)."},
                },
                "required": ["selector_or_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deep_search",
            "description": "Exhaustive multi-query search synthesizing multiple live sources with clean numbered citations and bibliography (Grok DeepSearch style).",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The research question or topic to deeply investigate."},
                    "sub_queries": {"type": "array", "items": {"type": "string"}, "description": "Optional list of 2-3 specific search query angles."},
                    "max_sources": {"type": "integer", "description": "Maximum number of unique sources to return (default 6)."},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "x_search",
            "description": "Real-time search of posts, discussions, and creator accounts on X (Twitter).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords, topic, or handles to search on X."},
                    "max_results": {"type": "integer", "description": "Maximum posts to return (default 8)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "x_trends",
            "description": "Scout current trending topics, discussions, and breaking themes on X (Twitter).",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_focus": {"type": "string", "description": "Category focus: 'tech', 'ai', 'business', 'local', or 'all' (default 'tech')."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "x_draft_thread",
            "description": "Draft a high-signal, punchy X (Twitter) thread without generic corporate or AI platitudes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Core subject or project build lesson."},
                    "tone": {"type": "string", "description": "Voice: 'high-signal', 'witty', 'technical', 'builder' (default 'high-signal')."},
                    "num_tweets": {"type": "integer", "description": "Number of tweets in thread (default 4)."},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_repl",
            "description": "Execute Python code inside the sandbox workspace and capture stdout, stderr, and execution duration (Grok Code Interpreter style).",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Complete Python script to run."},
                    "timeout_sec": {"type": "integer", "description": "Max runtime in seconds (default 20)."},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vm_exec",
            "description": "Execute a shell command inside the dedicated Linux Guest OS environment (own rootfs, networking, processes, and package manager).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run inside the Linux guest OS."},
                    "workdir": {"type": "string", "description": "Working directory inside the guest OS (default '/workspace')."},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds (default 60)."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vm_status",
            "description": "Inspect the Linux Guest OS status, including active backend, uptime, kernel, memory, and running containers/environments.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vm_install",
            "description": "Install packages (apt/apk/pip) inside the dedicated Linux Guest OS environment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "package": {"type": "string", "description": "Package name(s) to install (e.g. 'htop jq' or 'scikit-learn')."},
                },
                "required": ["package"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vm_restart",
            "description": "Restart the dedicated Linux Guest OS virtual environment.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute tool by name with arguments."""
    browser = get_browser()

    if name == "duckyscript":
        return run_duckyscript(
            script=args.get("script", ""),
            target=args.get("target", "browser"),
            vars=args.get("vars", None),
        )
    elif name == "browser_navigate":
        return browser.navigate(args.get("url", ""))
    elif name == "browser_click":
        return browser.click(args.get("selector", ""))
    elif name == "browser_type":
        return browser.type_text(
            selector=args.get("selector", ""),
            text=args.get("text", ""),
            press_enter=args.get("press_enter", False),
        )
    elif name == "browser_human_click":
        return browser.human_click(selector=args.get("selector", ""))
    elif name == "browser_human_type":
        return browser.human_type(
            selector=args.get("selector", ""),
            text=args.get("text", ""),
            press_enter=args.get("press_enter", False),
            clear_first=args.get("clear_first", True),
        )
    elif name == "browser_login":
        return browser.smart_login(
            url=args.get("url"),
            username=args.get("username"),
            password=args.get("password"),
            user_selector=args.get("user_selector"),
            pass_selector=args.get("pass_selector"),
            submit_selector=args.get("submit_selector"),
        )
    elif name == "browser_check_auth":
        return browser.check_auth(url_or_domain=args.get("url"))
    elif name == "browser_fill_form":
        return browser.fill_form(
            fields=args.get("fields", {}),
            submit_selector=args.get("submit_selector"),
        )
    elif name == "browser_takeover":
        return browser.open_takeover(
            url=args.get("url", "https://x.com"),
            reason=args.get("reason", ""),
        )
    elif name == "browser_scroll":
        return browser.scroll(
            direction=args.get("direction", "down"),
            amount=args.get("amount", 500),
        )
    elif name == "browser_extract":
        return browser.extract_content(max_chars=args.get("max_chars", 8000))
    elif name == "browser_screenshot":
        return browser.screenshot(filename=args.get("filename", "screenshot.png"))
    elif name == "browser_session_export":
        return browser.export_session(filepath=args.get("filepath"))
    elif name == "browser_session_import":
        return browser.import_session(filepath=args.get("filepath"))
    elif name == "browser_highlight":
        return browser.highlight_element(
            selector=args.get("selector", ""),
            duration_ms=args.get("duration_ms", 2500),
            color=args.get("color", "#1a73e8"),
            label=args.get("label"),
        )
    elif name == "browser_get_coordinates":
        return browser.get_element_coordinates(selector=args.get("selector", ""))
    elif name == "browser_list_interactive":
        return browser.get_interactive_elements_with_bounds(max_elements=args.get("max_elements", 50))
    elif name == "browser_wait_for":
        return browser.wait_for(
            selector_or_text=args.get("selector_or_text", ""),
            timeout_ms=args.get("timeout_ms", 10000),
        )
    elif name == "shell":
        return run_shell(command=args.get("command", ""))
    elif name == "read_file":
        return read_file(path=args.get("path", ""))
    elif name == "write_file":
        return write_file(path=args.get("path", ""), content=args.get("content", ""))
    elif name == "list_files":
        return list_files(path=args.get("path", "."))
    elif name == "web_search":
        return search_web(query=args.get("query", ""))
    elif name == "fetch_page":
        return fetch_page(url=args.get("url", ""))
    elif name == "save_memory":
        return save_memory(note=args.get("note", ""))
    elif name == "deep_search":
        return deep_search(
            topic=args.get("topic", ""),
            sub_queries=args.get("sub_queries"),
            max_sources=args.get("max_sources", 6),
        )
    elif name == "x_search":
        return search_x(
            query=args.get("query", ""),
            max_results=args.get("max_results", 8),
        )
    elif name == "x_trends":
        return scout_x_trends(topic_focus=args.get("topic_focus", "tech"))
    elif name == "x_draft_thread":
        return draft_x_thread(
            topic=args.get("topic", ""),
            tone=args.get("tone", "high-signal"),
            num_tweets=args.get("num_tweets", 4),
        )
    elif name == "python_repl":
        return run_python(
            code=args.get("code", ""),
            timeout_sec=args.get("timeout_sec", 20),
        )
    elif name == "vm_exec":
        return guest_os.run_command(
            command=args.get("command", ""),
            timeout=args.get("timeout", 60),
            workdir=args.get("workdir"),
        )
    elif name == "vm_status":
        return guest_os.get_status()
    elif name == "vm_install":
        return guest_os.install_package(package=args.get("package", ""))
    elif name == "vm_restart":
        return guest_os.restart()
    else:
        return {"ok": False, "error": f"Unknown tool '{name}'"}
