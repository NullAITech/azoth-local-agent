#!/usr/bin/env python3
"""aZoth-local — Autonomous Local Agent with Grok-Grade Intelligence & Multi-Engine Routing.

Inspired by and built to surpass Grok Bot:
- Real-time X / Twitter Intelligence & Trend Scouting
- DeepSearch Multi-Source Parallel Synthesis with Citations
- Dynamic Grok Persona Modes: ⚡ Regular (Truth), 🌶️ Fun Mode, 🧠 DeepSearch & Think, 💻 Coder & Builder
- Chain-of-Thought (<think>...</think>) Extraction & Visualization
- Persistent Sandboxed Browser ("VM-ish vibes") with Authenticated Sessions
- Safe Workspace Shell & Python Code Interpreter
- Multi-Engine Routing: Ollama, Grok (CLI & API), Hermes, AGY, Codex, Gemini, Claude
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

try:
    from rich import print as rprint
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

from tools.browser import get_browser
from tools.code_runner import run_python
from tools.deep_search import deep_search
from tools.definitions import AGENT_TOOLS, execute_tool
from tools.workspace import WORKSPACE_DIR
from tools.x_intelligence import draft_x_thread, scout_x_trends, search_x
from engines.manager import EngineRegistry, EnvConfigManager, execute_cli_agent, execute_cli_agent_stream
from prompts.modes import DEFAULT_MODE, MODES, get_mode, list_modes

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
MEMORY_PATH = ROOT / "MEMORY.md"
SYSTEM_PATH = PROMPTS / "system.md"

COMMANDS = {
    "/mode [name]": "Switch Grok mode: regular (⚡), fun (🌶️), think (🧠), coder (💻)",
    "/modes": "List all agent personality & reasoning modes",
    "/fun": "Quick toggle to Grok Fun Mode (witty, irreverent, sharp)",
    "/think": "Quick toggle to DeepSearch & Think Mode (chain-of-thought + citations)",
    "/coder": "Quick toggle to Coder & Builder Mode (sandbox scripting & execution)",
    "/regular": "Quick toggle to Truth & Regular Mode (objective, direct)",
    "/deep [topic]": "Run a multi-source DeepSearch with verifiable citations",
    "/x [query]": "Search live posts, discussions, and handles on X (Twitter)",
    "/trends [topic]": "Scout trending topics and discussions on X",
    "/py [code]": "Execute Python code in the sandbox workspace",
    "/vm [cmd]": "Inspect Linux Guest OS status or execute shell command inside it",
    "/os [cmd]": "Alias for /vm",
    "/engine [name]": "Switch active engine (ollama, hermes, agy, codex, grok_cli, xai, openai, gemini, openrouter)",
    "/engines": "List all installed engines, CLIs, and their status",
    "/config": "Inspect active .env configuration and API key status",
    "/key [NAME] [VAL]": "Save or update an API key in .env (e.g. /key XAI_API_KEY xai-...)",
    "/browser [url]": "Launch visible Sandboxed Chrome window to log into services",
    "/workspace": "List files in the sandbox workspace directory",
    "/tools": "List all active agent tools and parameter schemas",
    "/model [name]": "View or switch active LLM model",
    "/memory": "Show MEMORY.md contents",
    "/clear": "Clear conversation history (keeps system prompt + memory + mode)",
    "/help": "Show this command guide",
    "/quit or /exit": "Exit the agent",
}


def load_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(mode: Optional[str] = None) -> str:
    system = load_text(SYSTEM_PATH)
    if not system:
        system = "You are aZoth-local, an autonomous AI agent with a sandboxed browser, workspace, and live web intelligence."

    mode_obj = get_mode(mode or EnvConfigManager.get("AGENT_MODE", DEFAULT_MODE))
    system = f"{system}\n\n---\n{mode_obj.instructions}"

    memory = load_text(MEMORY_PATH)
    if memory:
        system = f"{system}\n\n---\n# Loaded MEMORY.md\n{memory}"
    return system


def extract_thinking(text: str) -> tuple[Optional[str], str]:
    """Extract <think>...</think> chain-of-thought blocks from model output."""
    if not text:
        return None, ""
    match = re.search(r"<think>(.*?)</think>", text, re.DOTALL | re.IGNORECASE)
    if match:
        thinking = match.group(1).strip()
        clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return thinking, clean
    return None, text


def make_client() -> tuple[OpenAI, str, str]:
    EnvConfigManager.load()
    api_key = (
        os.getenv("XAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "ollama"
    )
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("MODEL", "qwen2.5-coder:1.5b")
    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model, base_url


def render_banner(engine: str, model: str, mode: str):
    mode_obj = get_mode(mode)
    if HAS_RICH:
        banner = (
            f"[bold cyan]aZoth-local[/bold cyan] [green]v2.5[/green] — [bold white]Autonomous Local Agent (Grok-Grade Intelligence)[/bold white]\n"
            f"[dim]Engine:[/dim] [yellow]{engine}[/yellow]  |  [dim]Model:[/dim] [cyan]{model}[/cyan]  |  [dim]Mode:[/dim] [magenta]{mode_obj.icon} {mode_obj.name}[/magenta]\n"
            f"[dim]Capabilities:[/dim] [white]Live X Scouting • DeepSearch Citations • Browser Sandbox • Python REPL[/white]\n"
            f"[dim]Sandbox:[/dim] [magenta]{WORKSPACE_DIR}[/magenta]\n\n"
            f"[italic white]Supported: [cyan]Ollama (Offline)[/cyan] • [yellow]Hermes[/yellow] • [green]AGY[/green] • [blue]Codex[/blue] • [red]xAI Grok[/red] • [magenta]Claude[/magenta] • [blue]Gemini[/blue][/italic white]"
        )
        console.print(Panel(banner, border_style="cyan", title="⚡ aZoth Agent Active ⚡"))
    else:
        print("=" * 70)
        print(f"aZoth-local v2.5 — Autonomous Local Agent (Grok-Grade Intelligence)")
        print(f"Engine: {engine} | Model: {model} | Mode: {mode_obj.icon} {mode_obj.name}")
        print("Capabilities: Live X Scouting • DeepSearch Citations • Browser Sandbox • Python REPL")
        print("Supported: Ollama • Hermes • AGY • Codex • Grok • Claude • Gemini")
        print("=" * 70 + "\n")


def cmd_modes(active_mode: str):
    modes = list_modes()
    if HAS_RICH:
        table = Table(title="aZoth / Grok Operating Modes", border_style="magenta")
        table.add_column("ID", style="bold yellow")
        table.add_column("Mode Name", style="white")
        table.add_column("Icon", style="cyan")
        table.add_column("Tagline", style="dim")
        table.add_column("Status", style="green")
        for m in modes:
            status = "[bold green]ACTIVE[/bold green]" if m["id"] == active_mode else "[dim]inactive[/dim]"
            table.add_row(m["id"], m["name"], m["icon"], m["tagline"], status)
        console.print(table)
    else:
        print("\nOperating Modes:")
        for m in modes:
            cur = " (ACTIVE)" if m["id"] == active_mode else ""
            print(f"  {m['id']:10} {m['icon']} {m['name']:22} - {m['tagline']}{cur}")
        print()


def cmd_engines():
    engines = EngineRegistry.get_available_engines()
    if HAS_RICH:
        table = Table(title="Available Agent Engines & CLIs", border_style="cyan")
        table.add_column("ID", style="bold yellow")
        table.add_column("Engine Name", style="white")
        table.add_column("Type", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details", style="dim")
        for e in engines:
            status = "[green]Available[/green]" if e["available"] else "[red]Not Configured[/red]"
            details = e.get("path") or ", ".join(e.get("models", [])[:2])
            table.add_row(f"{e.get('icon', '')} {e['id']}", e["name"], e["type"], status, details)
        console.print(table)
    else:
        print("\nEngines:")
        for e in engines:
            st = "Available" if e["available"] else "Not Configured"
            print(f"  {e['id']:12} {e['name']:25} [{st}]")
        print()


def cmd_config():
    configs = EnvConfigManager.get_masked_configs()
    if HAS_RICH:
        table = Table(title="Active Engine & API Configuration (.env)", border_style="cyan")
        table.add_column("Variable", style="bold yellow")
        table.add_column("Value / Status", style="white")
        for k, v in configs.items():
            if k.endswith("_configured"):
                continue
            table.add_row(k, str(v) if v else "[dim]Not Set[/dim]")
        console.print(table)
    else:
        print("\nConfiguration:")
        for k, v in configs.items():
            if not k.endswith("_configured"):
                print(f"  {k:25} = {v or 'Not Set'}")
        print()


def cmd_help():
    if HAS_RICH:
        table = Table(title="aZoth-local Agent Commands", border_style="dim")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        for cmd, desc in COMMANDS.items():
            table.add_row(cmd, desc)
        console.print(table)
    else:
        print("\nCommands:")
        for cmd, desc in COMMANDS.items():
            print(f"  {cmd:20} {desc}")
        print()


def cmd_deep(topic: str):
    """Run interactive DeepSearch directly from CLI."""
    if not topic.strip():
        print("Usage: /deep [topic to investigate]")
        return
    if HAS_RICH:
        console.print(f"\n[bold cyan]🧠 DeepSearch Vectorizing:[/bold cyan] [white]{topic}[/white]...")
    else:
        print(f"\nDeepSearch: {topic}...")

    res = deep_search(topic=topic, max_sources=6, fetch_top_pages=True)
    if not res.get("ok"):
        print(f"DeepSearch error: {res.get('error')}")
        return

    sources = res.get("sources", [])
    if HAS_RICH:
        table = Table(title=f"📚 DeepSearch Sources ({len(sources)} verified)", border_style="cyan")
        table.add_column("#", style="bold yellow", width=4)
        table.add_column("Source Title", style="white")
        table.add_column("Domain", style="cyan")
        table.add_column("Snippet Preview", style="dim")
        for s in sources:
            table.add_row(str(s["index"]), s["title"][:50], s["domain"], s["snippet"][:70] + "...")
        console.print(table)
    else:
        print(f"\nFound {len(sources)} Sources:")
        for s in sources:
            print(f"  [{s['index']}] {s['title']} ({s['domain']}) -> {s['url']}")
    print()


def cmd_x(query: str):
    """Run interactive X search directly from CLI."""
    if not query.strip():
        print("Usage: /x [keywords or @handle]")
        return
    if HAS_RICH:
        console.print(f"\n[bold cyan]🐦 Live X Scouting:[/bold cyan] [white]{query}[/white]...")
    else:
        print(f"\nLive X Scouting: {query}...")

    res = search_x(query=query, max_results=6)
    posts = res.get("posts", [])
    if HAS_RICH:
        table = Table(title=f"🐦 Live Posts on X ({len(posts)} found)", border_style="blue")
        table.add_column("Handle", style="bold cyan", width=16)
        table.add_column("Title / Snippet", style="white")
        table.add_column("URL", style="dim")
        for p in posts:
            table.add_row(p["handle"], p["content"][:80] + "...", p["url"][:45] + "...")
        console.print(table)
    else:
        print(f"\nFound {len(posts)} Posts on X:")
        for p in posts:
            print(f"  {p['handle']}: {p['content'][:80]} -> {p['url']}")
    print()


def cmd_py(code: str):
    """Run sandbox Python code directly from CLI."""
    if not code.strip():
        print("Usage: /py [python code or one-liner]")
        return
    res = run_python(code=code, timeout_sec=20)
    if HAS_RICH:
        style = "green" if res.get("ok") else "red"
        console.print(Panel(res.get("output", "").strip() or "(no output)", title=f"🐍 Python Execution ({res.get('elapsed_seconds')}s)", border_style=style))
    else:
        print(f"Python ({res.get('elapsed_seconds')}s):\n{res.get('output')}")


def cmd_vm(cmd: str = ""):
    """Inspect or run commands inside the isolated Linux Guest OS."""
    from tools.vm_manager import guest_os
    if not cmd.strip():
        status = guest_os.get_status()
        if HAS_RICH:
            table = Table(title="⚡ aZoth Linux Guest OS Status", border_style="cyan")
            table.add_column("Property", style="bold cyan")
            table.add_column("Value", style="white")
            table.add_row("Backend", status.get("backend", "unknown"))
            table.add_row("Running", str(status.get("running")))
            table.add_row("Container / VM", status.get("container_name", "unknown"))
            table.add_row("Hostname", status.get("hostname", "unknown"))
            table.add_row("OS Release", status.get("os_release", "unknown"))
            table.add_row("Kernel", status.get("kernel", "unknown"))
            table.add_row("Memory", status.get("memory", "unknown"))
            table.add_row("Storage", status.get("disk", "unknown"))
            table.add_row("Workspace Mount", status.get("workspace_dir", "unknown"))
            console.print(table)
        else:
            print("\n⚡ aZoth Linux Guest OS Status:")
            for k, v in status.items():
                print(f"  • {k:15}: {v}")
            print()
    else:
        if HAS_RICH:
            console.print(f"\n[bold cyan]⚡ Running in Guest OS:[/bold cyan] [white]{cmd}[/white]")
        else:
            print(f"\n⚡ Running in Guest OS: {cmd}")
        res = guest_os.run_command(cmd)
        if res.get("stdout"):
            print(res["stdout"])
        if res.get("stderr"):
            print(f"stderr: {res['stderr']}")
        print(f"[{res.get('exit_code', 0)} in {res.get('duration_ms', 0)}ms]\n")


def agent_step(client: OpenAI, model: str, messages: list[dict], max_turns: int = 8) -> str:
    """Run an agentic ReAct loop supporting multiple tool calls and thought rendering."""
    turns = 0
    while turns < max_turns:
        turns += 1
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            if "tool" in str(e).lower() or "not supported" in str(e).lower():
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                )
                raw_text = resp.choices[0].message.content or ""
                thinking, clean_reply = extract_thinking(raw_text)
                if thinking and HAS_RICH:
                    console.print(Panel(Markdown(thinking), title="🧠 Grok-Style Thinking Chain", border_style="yellow", expand=False))
                return clean_reply
            raise e

        msg = response.choices[0].message
        tool_calls = msg.tool_calls

        if not tool_calls:
            raw_content = msg.content or ""
            thinking, clean_reply = extract_thinking(raw_content)
            if thinking and HAS_RICH:
                console.print(Panel(Markdown(thinking), title="🧠 Grok-Style Thinking Chain", border_style="yellow", expand=False))
            return clean_reply

        messages.append(msg.model_dump())

        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except Exception:
                fn_args = {}

            if HAS_RICH:
                args_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in fn_args.items())
                console.print(f"  [dim cyan]⚡ Tool Call:[/dim cyan] [bold cyan]{fn_name}[/bold cyan]({args_preview})")
            else:
                print(f"  ⚡ Running tool: {fn_name}({fn_args})")

            try:
                tool_result = execute_tool(fn_name, fn_args)
            except Exception as e:
                tool_result = {"ok": False, "error": str(e)}

            result_str = json.dumps(tool_result, ensure_ascii=False)

            if HAS_RICH:
                summary = tool_result.get("summary") or tool_result.get("title") or ("Error: " + str(tool_result.get("error"))) if not tool_result.get("ok", True) else "Done"
                console.print(f"  [dim green]✔ Result:[/dim green] [dim]{summary}[/dim]")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": fn_name,
                "content": result_str,
            })

    return "Agent reached maximum tool iterations."


def main() -> int:
    parser = argparse.ArgumentParser(description="aZoth-local agent")
    parser.add_argument("--engine", type=str, default="ollama", help="Active engine (ollama, hermes, agy, codex, grok_cli, xai, etc.)")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--mode", type=str, default="regular", help="Agent mode: regular, fun, think, coder")
    parser.add_argument("--web", action="store_true", help="Launch web UI cockpit")
    args = parser.parse_args()

    if args.web:
        try:
            import uvicorn
            from web_ui import app
            print("Launching aZoth Web Cockpit at http://127.0.0.1:8790 (listening on 0.0.0.0)...")
            uvicorn.run("web_ui:app", host="0.0.0.0", port=8790, reload=False)
            return 0
        except Exception as e:
            print(f"Error starting web UI: {e}")
            return 1

    engine = args.engine
    active_mode = args.mode or EnvConfigManager.get("AGENT_MODE", DEFAULT_MODE)
    client, default_model, base_url = make_client()
    model = args.model or default_model
    render_banner(engine, model, active_mode)

    messages: list[dict] = [{"role": "system", "content": build_system_prompt(active_mode)}]

    while True:
        mode_icon = get_mode(active_mode).icon
        try:
            prompt_label = f"you ({engine} | {mode_icon} {active_mode})"
            if HAS_RICH:
                user = console.input(f"\n[bold green]{prompt_label}>[/bold green] ").strip()
            else:
                user = input(f"\n{prompt_label}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nShutting down aZoth-local.")
            get_browser().close()
            return 0

        if not user:
            continue

        low = user.lower()

        if low in ("/quit", "/exit"):
            print("Shutting down aZoth-local.")
            get_browser().close()
            return 0
        elif low == "/help":
            cmd_help()
            continue
        elif low == "/modes":
            cmd_modes(active_mode)
            continue
        elif low == "/engines":
            cmd_engines()
            continue
        elif low == "/config":
            cmd_config()
            continue
        elif low in ("/fun", "/mode fun"):
            active_mode = "fun"
            EnvConfigManager.set("AGENT_MODE", active_mode, persist=True)
            messages = [{"role": "system", "content": build_system_prompt(active_mode)}]
            print("Switched to Grok Fun Mode 🌶️ (Witty, sharp, and unfiltered)")
            continue
        elif low in ("/think", "/mode think"):
            active_mode = "think"
            EnvConfigManager.set("AGENT_MODE", active_mode, persist=True)
            messages = [{"role": "system", "content": build_system_prompt(active_mode)}]
            print("Switched to DeepSearch & Think Mode 🧠 (Exhaustive reasoning & citations)")
            continue
        elif low in ("/coder", "/mode coder"):
            active_mode = "coder"
            EnvConfigManager.set("AGENT_MODE", active_mode, persist=True)
            messages = [{"role": "system", "content": build_system_prompt(active_mode)}]
            print("Switched to Coder & Builder Mode 💻 (Sandbox scripting & engineering)")
            continue
        elif low in ("/regular", "/mode regular"):
            active_mode = "regular"
            EnvConfigManager.set("AGENT_MODE", active_mode, persist=True)
            messages = [{"role": "system", "content": build_system_prompt(active_mode)}]
            print("Switched to Truth & Regular Mode ⚡ (Objective & direct)")
            continue
        elif low.startswith("/mode"):
            parts = user.split(maxsplit=1)
            if len(parts) > 1:
                target_mode = parts[1].strip().lower()
                if target_mode in MODES:
                    active_mode = target_mode
                    EnvConfigManager.set("AGENT_MODE", active_mode, persist=True)
                    messages = [{"role": "system", "content": build_system_prompt(active_mode)}]
                    print(f"Switched mode to: {get_mode(active_mode).name} {get_mode(active_mode).icon}")
                else:
                    print(f"Unknown mode '{target_mode}'. Valid: {', '.join(MODES.keys())}")
            else:
                cmd_modes(active_mode)
            continue
        elif low.startswith("/deep"):
            parts = user.split(maxsplit=1)
            cmd_deep(parts[1] if len(parts) > 1 else "")
            continue
        elif low.startswith("/x"):
            parts = user.split(maxsplit=1)
            cmd_x(parts[1] if len(parts) > 1 else "")
            continue
        elif low.startswith("/trends"):
            parts = user.split(maxsplit=1)
            topic = parts[1] if len(parts) > 1 else "tech"
            res = scout_x_trends(topic_focus=topic)
            print(f"Trends ({topic}):")
            for t in res.get("trends", [])[:5]:
                print(f"  • {t.get('content')[:100]} ({t.get('url')})")
            continue
        elif low.startswith("/py"):
            parts = user.split(maxsplit=1)
            cmd_py(parts[1] if len(parts) > 1 else "")
            continue
        elif low.startswith("/vm") or low.startswith("/os"):
            parts = user.split(maxsplit=1)
            cmd_vm(parts[1] if len(parts) > 1 else "")
            continue
        elif low.startswith("/key"):
            parts = user.split(maxsplit=2)
            if len(parts) == 3:
                k, v = parts[1].strip().upper(), parts[2].strip()
                EnvConfigManager.set(k, v, persist=True)
                print(f"Saved {k} to .env")
                client, default_model, base_url = make_client()
            else:
                print("Usage: /key VARIABLE_NAME value")
            continue
        elif low.startswith("/engine"):
            parts = user.split(maxsplit=1)
            if len(parts) > 1:
                engine = parts[1].strip().lower()
                EnvConfigManager.set("ACTIVE_ENGINE", engine, persist=True)
                print(f"Active engine switched to: {engine}")
            else:
                cmd_engines()
            continue
        elif low.startswith("/model"):
            parts = user.split(maxsplit=1)
            if len(parts) > 1:
                model = parts[1].strip()
                EnvConfigManager.set("MODEL", model, persist=True)
                print(f"Model switched to: {model}")
                client, default_model, base_url = make_client()
            else:
                print(f"Current model: {model}")
            continue
        elif low.startswith("/browser") or low.startswith("/login"):
            parts = user.split(maxsplit=1)
            target_url = parts[1] if len(parts) > 1 else "https://x.com"
            res = get_browser().open_takeover_window(target_url)
            print(res.get("message", "Browser opened."))
            continue
        elif low == "/clear":
            messages = [{"role": "system", "content": build_system_prompt(active_mode)}]
            print("Conversation history cleared.")
            continue

        # CLI Engine Execution with Real-Time Streaming Output & Fallback
        if engine in ("hermes", "agy", "codex", "grok_cli", "gemini", "claude"):
            if HAS_RICH:
                console.print(f"\n[bold yellow]{engine}[/bold yellow] 🚀 streaming output from sandbox workspace...")
            else:
                print(f"\n{engine} running...")

            def print_chunk(chunk_text: str):
                if HAS_RICH:
                    console.print(chunk_text, end="")
                else:
                    sys.stdout.write(chunk_text)
                    sys.stdout.flush()

            res = execute_cli_agent(
                engine_id=engine,
                prompt=user,
                on_chunk=print_chunk,
                auto_fallback=True,
            )

            if res.get("fallback_used"):
                if HAS_RICH:
                    console.print(f"\n[bold green]✔ Fallback succeeded using {res['fallback_used']}[/bold green]")
                else:
                    print(f"\n✔ Fallback succeeded using {res['fallback_used']}")
            elif not res.get("ok"):
                err = res.get("error", "Execution failed")
                if "402" in err or "balance exhausted" in err.lower():
                    if HAS_RICH:
                        console.print(f"\n[bold yellow]Notice:[/bold yellow] Grok CLI usage balance is exhausted. You can use local Ollama with [cyan]/engine ollama[/cyan] or set an xAI key with [cyan]/key XAI_API_KEY xai-...[/cyan]")
                    else:
                        print("\nNotice: Grok CLI usage balance is exhausted. Switch with /engine ollama or configure /key XAI_API_KEY")
                else:
                    if HAS_RICH:
                        console.print(f"\n[bold red][Error][/bold red] {err}")
                    else:
                        print(f"\n[Error] {err}")
            print()
            continue

        # API Engine Execution (ReAct Tool Loop)
        messages.append({"role": "user", "content": user})
        if HAS_RICH:
            console.print(f"\n[bold cyan]aZoth ({get_mode(active_mode).icon} {active_mode})[/bold cyan] 🧠 thinking...")
        else:
            print(f"\naZoth ({active_mode})> thinking...")

        try:
            reply = agent_step(client, model, messages)
            messages.append({"role": "assistant", "content": reply})

            if HAS_RICH:
                console.print(f"\n[bold cyan]aZoth ({get_mode(active_mode).icon} {active_mode})>[/bold cyan]")
                console.print(Markdown(reply))
            else:
                print(f"\naZoth ({active_mode})>\n{reply}")
        except Exception as e:
            if HAS_RICH:
                console.print(f"[bold red][Error][/bold red] {e}")
            else:
                print(f"[Error] {e}")
            messages.pop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
