"""DuckyScript & Hardware Input Automation Engine for a-bot.

Supports standard DuckyScript syntax and extended enterprise commands for zero-detection browser & OS automation:
- DELAY <ms>                 -> Pause execution for <ms> milliseconds
- RANDOM_DELAY <min> <max>   -> Pause for random duration between min and max ms (mimics human jitter)
- WAIT_FOR <selector/text> [timeout_ms] -> Wait for element selector or visible text on page
- SCREENSHOT <name>          -> Capture screenshot to sandbox/workspace/<name>
- REPLAY <macro_file>        -> Replay/include another macro file or preset with variable inheritance
- VAR <name>=<val>           -> Define a variable and substitute $NAME / ${NAME} across subsequent commands
- STRING / TYPE <text>       -> Type text with natural keystroke timing jitter
- ENTER / RETURN             -> Press Enter
- TAB, ESCAPE, SPACE         -> Press special key
- NAVIGATE <url>             -> Navigate browser tab to URL
- CLICK <x> <y> | <selector> -> Click coordinates (x, y) or click element by selector/text
- MOUSE_MOVE <x> <y>         -> Move mouse cursor
- SCROLL <delta>             -> Scroll page vertically (+ for down, - for up)
- CTRL+T [url]               -> Open new browser tab
- CTRL+W                     -> Close active tab
- CTRL+L                     -> Focus address bar
- CTRL+V / PASTE             -> Paste clipboard text
- CTRL+ENTER                 -> Submit post/form (e.g. X/Twitter, LinkedIn, forms)
- CLIPBOARD <text>           -> Copy text to system clipboard
- REPEAT <n>                 -> Repeat immediately preceding command n times
- LOG / ECHO <message>       -> Record diagnostic log message in execution history
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = ROOT / "sandbox"
WORKSPACE_DIR = SANDBOX_DIR / "workspace"
PRESETS_DIR = Path(__file__).resolve().parent / "presets"


def get_recovery_suggestion(cmd: str, arg: str, err: Exception, line: str) -> str:
    """Generate intelligent, actionable recovery suggestions based on the failed command."""
    err_str = str(err).lower()

    if cmd == "WAIT_FOR":
        if "timeout" in err_str or "timed out" in err_str:
            return (
                f"Element/text '{arg.split()[0] if arg else ''}' did not appear in time. "
                "Suggestions: (1) Increase the timeout: 'WAIT_FOR <target> 15000'. "
                "(2) Add 'DELAY 2000' prior to waiting for dynamic JavaScript. "
                "(3) Check if a login modal or CAPTCHA is blocking page rendering."
            )
        return (
            f"Failed waiting for '{arg}'. Suggestions: Ensure selector is valid CSS/XPath "
            "or pass plain text: 'WAIT_FOR \"Search\" 10000'."
        )

    elif cmd == "CLICK":
        if re.match(r"^\d+\s+\d+$", arg.strip()):
            return (
                f"Click at coordinates ({arg}) failed. Suggestions: (1) Verify sandboxed viewport "
                "resolution is 1280x800. (2) Use a CSS selector or button text instead: 'CLICK button[type=\"submit\"]'."
            )
        return (
            f"Click on target '{arg}' failed. Suggestions: (1) Verify element exists on page using "
            "'WAIT_FOR <selector>'. (2) Check if element is hidden behind a modal overlay or dropdown."
        )

    elif cmd == "REPLAY":
        if "recursion" in err_str or "circular" in err_str or "depth" in err_str:
            return (
                "Circular REPLAY loop or recursion depth limit exceeded (max 10). "
                "Suggestions: Check macro call chain and avoid recursive self-inclusion."
            )
        return (
            f"Macro '{arg}' could not be located. Suggestions: (1) Verify file exists in tools/presets/ "
            "or sandbox/workspace/. (2) Use preset ID (e.g. 'REPLAY x_post') or full filename."
        )

    elif cmd == "VAR":
        return (
            f"Invalid variable declaration on line: '{line}'. "
            "Suggestions: Use format 'VAR NAME=VALUE' (e.g. 'VAR SEARCH_TERM=plumbing') or quote values with spaces."
        )

    elif cmd == "RANDOM_DELAY":
        return (
            f"Invalid RANDOM_DELAY arguments '{arg}'. "
            "Suggestions: Specify minimum and maximum delay in milliseconds (e.g. 'RANDOM_DELAY 1000 3000')."
        )

    elif cmd == "DELAY":
        return (
            f"Invalid DELAY argument '{arg}'. "
            "Suggestions: Specify integer milliseconds (e.g. 'DELAY 1500')."
        )

    elif cmd == "NAVIGATE":
        return (
            f"Navigation to '{arg}' failed. Suggestions: (1) Ensure URL includes protocol (e.g. 'https://...'). "
            "(2) Verify sandboxed Chrome browser is running and connected."
        )

    elif cmd == "SCREENSHOT":
        return (
            f"Failed to capture screenshot to '{arg}'. Suggestions: (1) Verify destination workspace directory is writable. "
            "(2) Ensure browser page is loaded and not closed."
        )

    elif cmd in ("STRING", "TYPE", "WRITE"):
        return (
            "Typing failed. Suggestions: (1) Focus the target input box first using 'CLICK <selector>' or 'WAIT_FOR'. "
            "(2) If in OS mode, verify xdotool is installed."
        )

    return (
        f"Command '{cmd}' encountered an error. Suggestions: Check syntax, verify browser state, "
        "or review execution logs."
    )


def expand_variables(text: str, variables: Dict[str, str]) -> str:
    """Expand $VAR and ${VAR} placeholders with variable dictionary values and built-ins."""
    if not text:
        return text

    # Add dynamic built-in variables if not overridden
    builtins = {
        "TIMESTAMP": time.strftime("%Y-%m-%d %H:%M:%S"),
        "DATE": time.strftime("%Y-%m-%d"),
        "TIME": time.strftime("%H:%M:%S"),
        "RANDOM": str(random.randint(1000, 9999)),
        "WORKSPACE": str(WORKSPACE_DIR),
    }
    all_vars = {**builtins, **variables}

    def replace_curly(match: re.Match) -> str:
        var_name = match.group(1)
        return all_vars.get(var_name, match.group(0))

    def replace_simple(match: re.Match) -> str:
        var_name = match.group(1)
        return all_vars.get(var_name, match.group(0))

    # Match ${VAR_NAME}
    result = re.sub(r"\$\{([a-zA-Z0-9_]+)\}", replace_curly, text)
    # Match $VAR_NAME
    result = re.sub(r"\$([a-zA-Z0-9_]+)", replace_simple, result)
    return result


def parse_var_declaration(arg_line: str) -> Tuple[str, str]:
    """Parse 'NAME=VALUE' or 'NAME = VALUE' variable definitions."""
    if "=" in arg_line:
        name, val = arg_line.split("=", 1)
        name = name.strip()
        val = val.strip()
        # Remove surrounding matching quotes if present
        if len(val) >= 2 and (
            (val.startswith('"') and val.endswith('"')) or
            (val.startswith("'") and val.endswith("'"))
        ):
            val = val[1:-1]
        return name, val
    else:
        # Standalone variable name initialized to empty string
        return arg_line.strip(), ""


def load_preset_file(file_path: Path) -> dict[str, Any]:
    """Extract metadata and script content from a DuckyScript preset file."""
    content = file_path.read_text(encoding="utf-8")
    preset_id = file_path.stem
    title = preset_id.replace("_", " ").title()
    description = f"Macro preset loaded from {file_path.name}"
    tags = []
    variables = []

    for line in content.splitlines():
        line_clean = line.strip()
        if line_clean.startswith("REM Title:"):
            title = line_clean.split(":", 1)[1].strip()
        elif line_clean.startswith("REM Description:"):
            description = line_clean.split(":", 1)[1].strip()
        elif line_clean.startswith("REM Tags:"):
            tags = [t.strip() for t in line_clean.split(":", 1)[1].split(",") if t.strip()]
        elif line_clean.startswith("REM Variables:"):
            variables = [v.strip() for v in line_clean.split(":", 1)[1].split(",") if v.strip()]
        elif line_clean.startswith("VAR "):
            var_name, _ = parse_var_declaration(line_clean[4:])
            if var_name and var_name not in variables:
                variables.append(var_name)

    return {
        "id": preset_id,
        "title": title,
        "description": description,
        "tags": tags,
        "variables": variables,
        "template": content,
        "path": str(file_path),
    }


def load_all_presets() -> list[dict[str, Any]]:
    """Scan and load all DuckyScript presets from tools/presets/ directory."""
    presets = []
    if PRESETS_DIR.exists():
        for p in sorted(PRESETS_DIR.glob("*.ducky")) + sorted(PRESETS_DIR.glob("*.txt")):
            try:
                presets.append(load_preset_file(p))
            except Exception:
                pass
    return presets


DUCKY_PRESETS = load_all_presets()


class DuckyScriptEngine:
    """Enterprise DuckyScript Execution Engine with Extended Syntax & Resilient Diagnostics."""

    def __init__(self, browser_instance: Optional[Any] = None):
        self.browser_instance = browser_instance
        self.has_xdotool = shutil.which("xdotool") is not None
        self.has_xclip = shutil.which("xclip") is not None
        self.has_scrot = shutil.which("scrot") is not None
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_browser(self) -> Any:
        if self.browser_instance is not None:
            return self.browser_instance
        from .browser import get_browser
        return get_browser()

    def resolve_macro_content(self, macro_name_or_path: str) -> Tuple[str, str]:
        """Resolve a macro by filename, preset ID, or path. Returns (resolved_id, content)."""
        target = macro_name_or_path.strip()

        # 1. Check direct file path
        p = Path(target)
        if p.exists() and p.is_file():
            return p.stem, p.read_text(encoding="utf-8")

        # 2. Check tools/presets/
        preset_candidates = [
            PRESETS_DIR / target,
            PRESETS_DIR / f"{target}.ducky",
            PRESETS_DIR / f"{target}.txt",
        ]
        for pc in preset_candidates:
            if pc.exists() and pc.is_file():
                return pc.stem, pc.read_text(encoding="utf-8")

        # 3. Check sandbox/workspace/
        workspace_candidates = [
            WORKSPACE_DIR / target,
            WORKSPACE_DIR / f"{target}.ducky",
            WORKSPACE_DIR / f"{target}.txt",
        ]
        for wc in workspace_candidates:
            if wc.exists() and wc.is_file():
                return wc.stem, wc.read_text(encoding="utf-8")

        # 4. Check in-memory DUCKY_PRESETS
        for preset in load_all_presets():
            if preset["id"] == target or preset["id"] == target.lower():
                return preset["id"], preset["template"]

        raise FileNotFoundError(
            f"Macro '{target}' could not be found in presets ({PRESETS_DIR}) or workspace ({WORKSPACE_DIR})."
        )

    def validate(self, script_content: str, initial_vars: Optional[Dict[str, str]] = None) -> dict[str, Any]:
        """Perform static syntax and argument validation without executing side effects."""
        lines = script_content.strip().splitlines()
        errors = []
        warnings = []
        vars_map: Dict[str, str] = dict(initial_vars or {})
        vars_defined = set(vars_map.keys())
        valid_commands = {
            "REM", "#", "//", "DELAY", "RANDOM_DELAY", "WAIT_FOR", "SCREENSHOT",
            "REPLAY", "VAR", "STRING", "TYPE", "WRITE", "ENTER", "RETURN",
            "TAB", "ESCAPE", "SPACE", "BACKSPACE", "DELETE", "UP", "DOWN",
            "LEFT", "RIGHT", "PAGE_UP", "PAGE_DOWN", "HOME", "END",
            "NAVIGATE", "CTRL+T", "CTRL+W", "CTRL+L", "CTRL+V", "PASTE",
            "CTRL+C", "COPY", "CTRL+A", "CTRL+ENTER", "CTRL+RETURN",
            "CLIPBOARD", "CLICK", "MOUSE_MOVE", "SCROLL", "REPEAT",
            "LOG", "ECHO"
        }

        for idx, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line or line.startswith("REM") or line.startswith("#") or line.startswith("//"):
                continue

            expanded_line = expand_variables(line, vars_map)
            parts = expanded_line.split(maxsplit=1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            # Check general shortcuts (e.g. CTRL+SHIFT+I, ALT+F4)
            is_shortcut = "+" in cmd

            if cmd not in valid_commands and not is_shortcut:
                errors.append({
                    "line_number": idx,
                    "line_content": line,
                    "command": cmd,
                    "error": f"Unknown command '{cmd}'",
                    "suggestion": get_recovery_suggestion(cmd, arg, Exception("Unknown command"), line),
                })
                continue

            if cmd == "VAR":
                if not arg:
                    errors.append({
                        "line_number": idx,
                        "line_content": line,
                        "command": cmd,
                        "error": "VAR requires 'NAME=VALUE'",
                        "suggestion": "Specify variable assignment, e.g., 'VAR QUERY=developer'.",
                    })
                else:
                    var_name, var_val = parse_var_declaration(arg)
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", var_name):
                        errors.append({
                            "line_number": idx,
                            "line_content": line,
                            "command": cmd,
                            "error": f"Invalid variable name '{var_name}'",
                            "suggestion": "Variable names must start with a letter or underscore and contain only alphanumeric characters.",
                        })
                    else:
                        vars_defined.add(var_name)
                        vars_map[var_name] = var_val

            elif cmd == "DELAY":
                if not arg.isdigit() and not arg.startswith("$"):
                    errors.append({
                        "line_number": idx,
                        "line_content": line,
                        "command": cmd,
                        "error": f"DELAY requires integer milliseconds, got '{arg}'",
                        "suggestion": "Use integer milliseconds, e.g. 'DELAY 1500'.",
                    })

            elif cmd == "RANDOM_DELAY":
                toks = arg.split()
                if len(toks) < 2:
                    errors.append({
                        "line_number": idx,
                        "line_content": line,
                        "command": cmd,
                        "error": f"RANDOM_DELAY requires min and max integer ms, got '{arg}'",
                        "suggestion": "Provide two integer bounds: 'RANDOM_DELAY 500 2000'.",
                    })
                else:
                    t1, t2 = toks[0], toks[1]
                    t1_valid = t1.isdigit() or t1.startswith("$")
                    t2_valid = t2.isdigit() or t2.startswith("$")
                    if not (t1_valid and t2_valid):
                        errors.append({
                            "line_number": idx,
                            "line_content": line,
                            "command": cmd,
                            "error": f"RANDOM_DELAY requires min and max integer ms, got '{arg}'",
                            "suggestion": "Provide two integer bounds: 'RANDOM_DELAY 500 2000'.",
                        })
                    elif t1.isdigit() and t2.isdigit() and int(t1) > int(t2):
                        errors.append({
                            "line_number": idx,
                            "line_content": line,
                            "command": cmd,
                            "error": f"RANDOM_DELAY min ({t1}) cannot be greater than max ({t2})",
                            "suggestion": "Ensure minimum value precedes maximum value.",
                        })

            elif cmd == "REPLAY":
                if not arg:
                    errors.append({
                        "line_number": idx,
                        "line_content": line,
                        "command": cmd,
                        "error": "REPLAY requires a macro name or file path",
                        "suggestion": "Provide preset or path: 'REPLAY x_post'.",
                    })
                else:
                    try:
                        self.resolve_macro_content(arg)
                    except Exception as e:
                        warnings.append({
                            "line_number": idx,
                            "line_content": line,
                            "warning": str(e),
                        })

            elif cmd == "CLICK":
                if not arg:
                    errors.append({
                        "line_number": idx,
                        "line_content": line,
                        "command": cmd,
                        "error": "CLICK requires coordinates (x y) or target selector",
                        "suggestion": "Use 'CLICK 300 450' or 'CLICK button.submit'.",
                    })

        return {
            "ok": len(errors) == 0,
            "valid": len(errors) == 0,
            "total_lines": len(lines),
            "variables_defined": sorted(list(vars_defined)),
            "errors": errors,
            "warnings": warnings,
        }

    def execute(
        self,
        script_content: str,
        target: str = "browser",
        vars: Optional[Dict[str, str]] = None,
        overrides: Optional[Set[str]] = None,
        call_depth: int = 0,
        call_stack: Optional[List[str]] = None,
        max_depth: int = 10,
    ) -> dict[str, Any]:
        """Execute DuckyScript line by line with robust error diagnostics and macro recursion support."""
        if call_stack is None:
            call_stack = ["root"]

        if call_depth > max_depth:
            return {
                "ok": False,
                "error": f"Recursion limit reached (max_depth={max_depth}). Call stack: {' -> '.join(call_stack)}",
                "line_number": 1,
                "command": "REPLAY",
                "suggestion": get_recovery_suggestion("REPLAY", "", Exception("recursion depth"), ""),
                "executed_steps": [],
                "macro_stack": call_stack,
            }

        variables: Dict[str, str] = dict(vars or {})
        active_overrides: Set[str] = set(overrides) if overrides is not None else set(variables.keys())
        lines = script_content.splitlines()
        browser = self._get_browser() if target == "browser" else None
        executed_steps: List[str] = []
        last_action_line: Optional[Tuple[str, str]] = None  # for REPEAT

        for line_num, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line or line.startswith("REM") or line.startswith("#") or line.startswith("//"):
                continue

            # Expand variables in the raw line
            expanded_line = expand_variables(line, variables)
            parts = expanded_line.split(maxsplit=1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            # Step prefix tag for nested REPLAY logging
            prefix = f"[{call_stack[-1]}] " if len(call_stack) > 1 else ""

            try:
                # -------------------------------------------------------------
                # 1. Variables (VAR)
                # -------------------------------------------------------------
                if cmd == "VAR":
                    if not arg:
                        raise ValueError("VAR requires 'NAME=VALUE' assignment.")
                    var_name, var_val = parse_var_declaration(arg)
                    if var_name not in active_overrides:
                        variables[var_name] = var_val
                        if call_depth == 0:
                            active_overrides.add(var_name)
                    executed_steps.append(f"{prefix}VAR {var_name} = '{variables.get(var_name, var_val)}'")

                # -------------------------------------------------------------
                # 2. Timing & Delays (DELAY, RANDOM_DELAY)
                # -------------------------------------------------------------
                elif cmd == "DELAY":
                    ms = int(arg) if arg.isdigit() else 500
                    time.sleep(ms / 1000.0)
                    executed_steps.append(f"{prefix}DELAY {ms}ms")

                elif cmd == "RANDOM_DELAY":
                    tokens = arg.split()
                    if len(tokens) >= 2 and tokens[0].isdigit() and tokens[1].isdigit():
                        min_ms, max_ms = int(tokens[0]), int(tokens[1])
                    else:
                        min_ms, max_ms = 500, 1500
                    actual_ms = random.randint(min(min_ms, max_ms), max(min_ms, max_ms))
                    time.sleep(actual_ms / 1000.0)
                    executed_steps.append(f"{prefix}RANDOM_DELAY {actual_ms}ms ({min_ms}-{max_ms}ms)")

                # -------------------------------------------------------------
                # 3. Dynamic DOM Synchronization (WAIT_FOR)
                # -------------------------------------------------------------
                elif cmd == "WAIT_FOR":
                    if not arg:
                        raise ValueError("WAIT_FOR requires a selector, text, or timeout argument.")

                    # Parse optional trailing timeout integer (e.g. WAIT_FOR [data-testid="post"] 5000)
                    timeout_ms = 10000
                    target_spec = arg
                    tokens = arg.rsplit(maxsplit=1)
                    if len(tokens) == 2 and tokens[1].isdigit():
                        target_spec = tokens[0]
                        timeout_ms = int(tokens[1])

                    if target == "browser":
                        if hasattr(browser, "wait_for"):
                            res = browser.wait_for(target_spec, timeout_ms=timeout_ms)
                            if not res.get("ok"):
                                raise TimeoutError(res.get("error", f"Timeout waiting for '{target_spec}'"))
                        else:
                            # Fallback using current_page
                            page = browser.current_page
                            try:
                                page.wait_for_selector(target_spec, timeout=timeout_ms, state="visible")
                            except Exception:
                                page.get_by_text(target_spec).first.wait_for(timeout=timeout_ms, state="visible")
                    else:
                        # OS Target: Pause for safety
                        time.sleep(min(timeout_ms, 2000) / 1000.0)

                    executed_steps.append(f"{prefix}WAIT_FOR '{target_spec}' ({timeout_ms}ms)")

                # -------------------------------------------------------------
                # 4. State Capture (SCREENSHOT)
                # -------------------------------------------------------------
                elif cmd == "SCREENSHOT":
                    filename = arg.strip() if arg.strip() else f"screenshot_{int(time.time())}.png"
                    out_path = Path(filename)
                    if not out_path.is_absolute():
                        out_path = WORKSPACE_DIR / filename
                    out_path.parent.mkdir(parents=True, exist_ok=True)

                    if target == "browser":
                        if hasattr(browser, "screenshot"):
                            res = browser.screenshot(str(out_path))
                            if not res.get("ok"):
                                raise RuntimeError(res.get("error", "Browser screenshot capture failed"))
                        else:
                            page = browser.current_page
                            page.screenshot(path=str(out_path), full_page=False)
                    else:
                        # OS screenshot
                        if self.has_scrot:
                            subprocess.run(["scrot", str(out_path)], check=True)
                        else:
                            # Try PIL / pyautogui fallback if available
                            try:
                                import PIL.ImageGrab as ImageGrab
                                im = ImageGrab.grab()
                                im.save(str(out_path))
                            except Exception:
                                # Write placeholder file if no display capture tool installed
                                out_path.write_text(f"OS Screenshot recorded at {time.ctime()}", encoding="utf-8")

                    executed_steps.append(f"{prefix}SCREENSHOT -> {out_path.name}")

                # -------------------------------------------------------------
                # 5. Modular Composition (REPLAY)
                # -------------------------------------------------------------
                elif cmd == "REPLAY":
                    if not arg.strip():
                        raise ValueError("REPLAY requires a macro file or preset ID.")

                    macro_id, macro_content = self.resolve_macro_content(arg.strip())
                    if macro_id in call_stack:
                        raise RecursionError(f"Circular REPLAY detected: {' -> '.join(call_stack)} -> {macro_id}")

                    replay_res = self.execute(
                        script_content=macro_content,
                        target=target,
                        vars=variables,
                        overrides=active_overrides,
                        call_depth=call_depth + 1,
                        call_stack=call_stack + [macro_id],
                        max_depth=max_depth,
                    )

                    if not replay_res.get("ok"):
                        return replay_res

                    # Merge nested variables and steps
                    if "vars" in replay_res:
                        variables.update(replay_res["vars"])
                    executed_steps.extend(replay_res.get("executed_steps", []))

                # -------------------------------------------------------------
                # 6. Text Entry (STRING, TYPE, WRITE)
                # -------------------------------------------------------------
                elif cmd in ("STRING", "TYPE", "WRITE"):
                    if target == "browser":
                        browser.keyboard_type(arg)
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "type", "--delay", "15", arg])
                    display_text = arg[:30] + "..." if len(arg) > 30 else arg
                    executed_steps.append(f"{prefix}STRING '{display_text}'")

                # -------------------------------------------------------------
                # 7. Keyboard Navigation & Keys
                # -------------------------------------------------------------
                elif cmd in ("ENTER", "RETURN"):
                    if target == "browser":
                        browser.keyboard_press("Enter")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "Return"])
                    executed_steps.append(f"{prefix}ENTER")

                elif cmd == "TAB":
                    if target == "browser":
                        browser.keyboard_press("Tab")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "Tab"])
                    executed_steps.append(f"{prefix}TAB")

                elif cmd == "ESCAPE":
                    if target == "browser":
                        browser.keyboard_press("Escape")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "Escape"])
                    executed_steps.append(f"{prefix}ESCAPE")

                elif cmd == "SPACE":
                    if target == "browser":
                        browser.keyboard_press(" ")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "space"])
                    executed_steps.append(f"{prefix}SPACE")

                elif cmd in ("BACKSPACE", "DELETE"):
                    key_name = "Backspace" if cmd == "BACKSPACE" else "Delete"
                    if target == "browser":
                        browser.keyboard_press(key_name)
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", key_name])
                    executed_steps.append(f"{prefix}{cmd}")

                elif cmd in ("UP", "DOWN", "LEFT", "RIGHT", "ARROW_UP", "ARROW_DOWN", "ARROW_LEFT", "ARROW_RIGHT"):
                    dir_name = cmd.replace("ARROW_", "").capitalize()
                    key_mapped = f"Arrow{dir_name}"
                    if target == "browser":
                        browser.keyboard_press(key_mapped)
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", dir_name])
                    executed_steps.append(f"{prefix}{cmd}")

                elif cmd in ("PAGE_UP", "PAGE_DOWN", "PAGEUP", "PAGEDOWN", "HOME", "END", "INSERT"):
                    key_map = {
                        "PAGE_UP": "PageUp",
                        "PAGEUP": "PageUp",
                        "PAGE_DOWN": "PageDown",
                        "PAGEDOWN": "PageDown",
                        "HOME": "Home",
                        "END": "End",
                        "INSERT": "Insert",
                    }
                    key_name = key_map.get(cmd, cmd)
                    if target == "browser":
                        browser.keyboard_press(key_name)
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", key_name])
                    executed_steps.append(f"{prefix}{cmd}")

                # -------------------------------------------------------------
                # 8. Browser Navigation & Tabs (NAVIGATE, CTRL+T, CTRL+W, CTRL+L)
                # -------------------------------------------------------------
                elif cmd == "NAVIGATE":
                    if target == "browser":
                        browser.navigate(arg)
                    executed_steps.append(f"{prefix}NAVIGATE {arg}")

                elif cmd == "CTRL+T":
                    if target == "browser":
                        url = arg.strip() if arg.strip() else "https://google.com"
                        browser.new_tab(url)
                    executed_steps.append(f"{prefix}CTRL+T (New Tab)")

                elif cmd == "CTRL+W":
                    if target == "browser":
                        tabs = browser.list_tabs()
                        if tabs:
                            browser.close_tab(browser.active_page_index)
                    executed_steps.append(f"{prefix}CTRL+W (Close Tab)")

                elif cmd == "CTRL+L":
                    if target == "browser":
                        browser.current_page.keyboard.press("Control+L")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+l"])
                    executed_steps.append(f"{prefix}CTRL+L")

                # -------------------------------------------------------------
                # 9. Form & Shortcut Handling (CTRL+V, CTRL+ENTER, CTRL+C, CTRL+A)
                # -------------------------------------------------------------
                elif cmd in ("CTRL+V", "PASTE"):
                    if target == "browser":
                        browser.current_page.keyboard.press("Control+V")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
                    executed_steps.append(f"{prefix}CTRL+V (Paste)")

                elif cmd in ("CTRL+C", "COPY"):
                    if target == "browser":
                        browser.current_page.keyboard.press("Control+C")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+c"])
                    executed_steps.append(f"{prefix}CTRL+C (Copy)")

                elif cmd == "CTRL+A":
                    if target == "browser":
                        browser.current_page.keyboard.press("Control+A")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+a"])
                    executed_steps.append(f"{prefix}CTRL+A (Select All)")

                elif cmd in ("CTRL+ENTER", "CTRL+RETURN"):
                    if target == "browser":
                        browser.current_page.keyboard.press("Control+Enter")
                    else:
                        if self.has_xdotool:
                            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+Return"])
                    executed_steps.append(f"{prefix}CTRL+ENTER (Submit)")

                # -------------------------------------------------------------
                # 10. System Clipboard (CLIPBOARD)
                # -------------------------------------------------------------
                elif cmd == "CLIPBOARD":
                    if self.has_xclip:
                        p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                        p.communicate(input=arg.encode("utf-8"))
                    executed_steps.append(f"{prefix}CLIPBOARD '{arg[:20]}...'")

                # -------------------------------------------------------------
                # 11. Mouse Input (CLICK, MOUSE_MOVE, SCROLL)
                # -------------------------------------------------------------
                elif cmd == "CLICK":
                    coords_match = re.match(r"^(\d+)\s+(\d+)$", arg.strip())
                    if coords_match:
                        x, y = int(coords_match.group(1)), int(coords_match.group(2))
                        if target == "browser":
                            browser.mouse_click(x, y)
                        else:
                            if self.has_xdotool:
                                subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"])
                        executed_steps.append(f"{prefix}CLICK ({x}, {y})")
                    else:
                        # Target is selector or text
                        if target == "browser":
                            if hasattr(browser, "click"):
                                res = browser.click(arg.strip())
                                if not res.get("ok"):
                                    raise RuntimeError(res.get("error", f"Failed clicking target '{arg}'"))
                            else:
                                browser.current_page.click(arg.strip())
                        executed_steps.append(f"{prefix}CLICK '{arg.strip()}'")

                elif cmd == "MOUSE_MOVE":
                    coords = arg.split()
                    if len(coords) >= 2 and coords[0].isdigit() and coords[1].isdigit():
                        x, y = int(coords[0]), int(coords[1])
                        if target == "browser":
                            browser.mouse_move(x, y)
                        else:
                            if self.has_xdotool:
                                subprocess.run(["xdotool", "mousemove", str(x), str(y)])
                        executed_steps.append(f"{prefix}MOUSE_MOVE ({x}, {y})")

                elif cmd == "SCROLL":
                    delta = int(arg) if (arg.lstrip("-").isdigit()) else 300
                    if target == "browser":
                        browser.mouse_wheel(delta_y=delta)
                    else:
                        if self.has_xdotool:
                            btn = "5" if delta > 0 else "4"
                            subprocess.run(["xdotool", "click", btn])
                    executed_steps.append(f"{prefix}SCROLL {delta}")

                # -------------------------------------------------------------
                # 12. Diagnostics & Utilities (LOG, ECHO, REPEAT)
                # -------------------------------------------------------------
                elif cmd in ("LOG", "ECHO"):
                    executed_steps.append(f"{prefix}ℹ️ {arg}")

                elif cmd == "REPEAT":
                    count = int(arg) if arg.isdigit() else 1
                    if last_action_line:
                        sub_script = "\n".join([last_action_line[1]] * count)
                        sub_res = self.execute(
                            script_content=sub_script,
                            target=target,
                            vars=variables,
                            call_depth=call_depth,
                            call_stack=call_stack,
                            max_depth=max_depth,
                        )
                        if not sub_res.get("ok"):
                            return sub_res
                        executed_steps.extend(sub_res.get("executed_steps", []))

                # -------------------------------------------------------------
                # 13. General Modifier Shortcuts (e.g. ALT+F4, CTRL+SHIFT+P)
                # -------------------------------------------------------------
                else:
                    if "+" in cmd:
                        keys = cmd.lower()
                        if target == "browser":
                            browser.current_page.keyboard.press(keys)
                        else:
                            if self.has_xdotool:
                                subprocess.run(["xdotool", "key", "--clearmodifiers", keys])
                        executed_steps.append(f"{prefix}SHORTCUT {cmd}")
                    else:
                        raise ValueError(f"Unrecognized DuckyScript command '{cmd}'.")

                # Store for REPEAT
                if cmd not in ("REPEAT", "REM", "#", "//"):
                    last_action_line = (cmd, expanded_line)

            except Exception as e:
                err_msg = str(e)
                suggestion = get_recovery_suggestion(cmd, arg, e, line)
                return {
                    "ok": False,
                    "error": f"Error on line {line_num} ('{line}'): {err_msg}",
                    "line_number": line_num,
                    "line_content": line,
                    "command": cmd,
                    "suggestion": suggestion,
                    "executed_steps": executed_steps,
                    "vars": variables,
                    "macro_stack": call_stack,
                }

        return {
            "ok": True,
            "steps_count": len(executed_steps),
            "executed_steps": executed_steps,
            "vars": variables,
            "summary": f"Executed {len(executed_steps)} DuckyScript commands successfully.",
        }


_ducky_instance: Optional[DuckyScriptEngine] = None


def get_ducky_engine() -> DuckyScriptEngine:
    global _ducky_instance
    if _ducky_instance is None:
        _ducky_instance = DuckyScriptEngine()
    return _ducky_instance


def run_duckyscript(
    script: str,
    target: str = "browser",
    vars: Optional[Dict[str, str]] = None,
) -> dict[str, Any]:
    """Top-level convenience dispatcher for DuckyScript automation."""
    return get_ducky_engine().execute(script, target=target, vars=vars)
