# aZoth-local v2.5 — Autonomous Local Agent (Grok-Grade Intelligence)

An **autonomous local AI agent** engineered with **Grok-grade intelligence**: real-time X (Twitter) intelligence, multi-source DeepSearch with verifiable citations, dynamic Grok persona modes, chain-of-thought (`<think>`) reasoning, sandbox Python code interpreter, and persistent **Sandboxed Browser** ("VM-ish vibes" with zero VM overhead).

Built for Neal Frazier (Neal Frazier Tech, Virginia Beach) to run locally with **Ollama** (offline, private, free) or cloud models via **xAI Grok**, **Hermes**, **AGY**, **Codex**, **Claude**, or **Gemini**.

---

## 🚀 What Makes aZoth Like (and Better Than) Grok Bot

| Capability | Grok Bot (Cloud) | aZoth-local (Local Agent) |
|---|---|---|
| **Live X (Twitter) Search** | ✅ Cloud search | ✅ **Multi-engine live search + Authenticated Browser extraction** |
| **Grok Modes (Fun / Truth / Think / Coder)** | ✅ Server-side | ✅ **Dynamic local modes (⚡ Regular, 🌶️ Fun, 🧠 Think, 💻 Coder)** |
| **DeepSearch with Citations** | ✅ Server-side | ✅ **Parallel multi-query synthesis with numbered citations & source badges** |
| **Chain-of-Thought (`<think>`)** | ✅ Shown in UI | ✅ **Parsed & rendered in collapsible thought drawers (CLI & Web UI)** |
| **Python Code Interpreter** | ✅ Cloud sandbox | ✅ **Local sandbox workspace execution with instant stdout/stderr** |
| **Dedicated Linux Guest OS** | ❌ None | ✅ **Isolated containerized OS (`azoth-guest-os`) + rootfs, packages, and process tree** |
| **Interactive Browser Web Terminal** | ❌ None | ✅ **Full xterm.js PTY WebSocket terminal in Cockpit (`/ws/terminal`)** |
| **Persistent 2FA Browser ("VM vibes")** | ❌ None | ✅ **Dedicated Chrome profile with saved sessions & DuckyScript macros** |
| **Offline Privacy & Zero Cost** | ❌ Requires API credits | ✅ **100% free & offline via Ollama (`qwen2.5-coder`, `llama3.1`, `gemma4`)** |
| **Multi-Engine CLI Routing** | ❌ Single provider | ✅ **Auto-routes between Ollama, Grok CLI, Hermes, AGY, Codex, Claude** |

---

## ⚡ Grok Modes

Switch modes on the fly via CLI or the Web Cockpit:

1. **⚡ Truth & Regular Mode (`/regular` or `/mode regular`):**
   - Crisp, direct, objective, and grounded in verifiable reality. Zero corporate fluff or apologies.
2. **🌶️ Fun Mode (`/fun` or `/mode fun`):**
   - Classic Grok style: Witty, playful, irreverent, sharp, and unfiltered humor without sacrificing technical depth.
3. **🧠 DeepSearch & Think Mode (`/think` or `/mode think`):**
   - Exhaustive chain-of-thought reasoning, multi-angle source cross-referencing, and numbered inline citations (`[1]`, `[2]`).
4. **💻 Coder & Builder Mode (`/coder` or `/mode coder`):**
   - High-speed software engineering, sandbox script generation, automated testing, and execution.

---

## 🛠️ Tool Suite & Capabilities

1. **Live X (Twitter) Intelligence:**
   - `x_search(query)`: Search live posts, discussions, and handles on X.
   - `x_trends(topic_focus)`: Scout trending topics and breaking discussions.
   - `x_draft_thread(topic, tone)`: Draft high-signal, authentic X threads free of AI platitudes.
   - Browser authenticated post inspection for private threads.
2. **DeepSearch & Citation Engine:**
   - `deep_search(topic, sub_queries, max_sources)`: Runs parallel search vectors, deduplicates sources, and generates structured citation bibliographies.
3. **Python Code Interpreter:**
   - `python_repl(code, timeout_sec)`: Run Python scripts inside `sandbox/workspace/`, capturing stdout, stderr, execution duration, and file outputs.
4. **Persistent Sandboxed Browser ("VM-ish vibes"):**
   - Dedicated Chrome profile in `sandbox/browser_profile/`.
   - Log in once with 2FA (`/browser login https://x.com`), and sessions persist across runs.
   - Zero-API control: navigation, DOM extraction, clicks, inputs, screenshots, and session backup/restore.
5. **DuckyScript Hardware Macro Engine:**
   - Human-like mouse and keyboard automation with random delays, variables, and presets.
6. **Multi-Engine Routing & Auto-Fallback:**
   - Seamlessly switch between Ollama, Hermes Agent CLI, Google AGY, OpenAI Codex, xAI Grok (CLI & API), Gemini, and Claude Code.

---

## 🏁 Quick Start

### 1. Run with Local Ollama (Default & Offline)

Ensure Ollama is running (`ollama serve`), then run:

```bash
cd azoth-local-agent
python3 agent.py
```

### 2. Run the Web Cockpit UI

```bash
cd azoth-local-agent
python3 agent.py --web
```
Open **`http://127.0.0.1:8790`** in your browser.

### 3. Run with Grok Mode or Overrides

```bash
# Start directly in Grok Fun Mode
python3 agent.py --mode fun

# Start directly in DeepSearch & Think Mode
python3 agent.py --mode think

# Start with xAI Grok API
python3 agent.py --engine xai --model grok-2-latest
```

---

## 💻 REPL Commands

| Command | Action |
|---|---|
| `/mode [name]` | Switch Grok mode: `regular` (⚡), `fun` (🌶️), `think` (🧠), `coder` (💻) |
| `/modes` | Display all available operating modes and status |
| `/fun` | Quick toggle to Grok Fun Mode |
| `/think` | Quick toggle to DeepSearch & Think Mode |
| `/coder` | Quick toggle to Coder & Builder Mode |
| `/regular` | Quick toggle to Truth & Regular Mode |
| `/deep [topic]` | Run an exhaustive multi-source DeepSearch with citations |
| `/x [query]` | Search live posts, discussions, and handles on X (Twitter) |
| `/trends [topic]` | Scout trending topics and breaking themes on X |
| `/py [code]` | Execute Python code inside the sandbox workspace |
| `/vm [cmd]` | Inspect Linux Guest OS status or execute command inside the isolated OS |
| `/os [cmd]` | Alias for `/vm` |
| `/engine [name]` | Switch engine (`ollama`, `hermes`, `agy`, `codex`, `grok_cli`, `xai`, `gemini`, `claude`) |
| `/engines` | List installed CLI engines, paths, and status |
| `/browser [url]` | Launch visible headed Sandboxed Chrome window to log into services |
| `/workspace` | Inspect and list files in the sandbox workspace |
| `/tools` | List all active agent tools and schemas |
| `/model [name]` | View or switch active LLM model |
| `/clear` | Reset conversation history (keeps system prompt + memory + mode) |
| `/help` | Show command guide |
| `/quit` or `/exit` | Exit the agent |

---

## 📁 Directory Structure

```
azoth-local-agent/
├── agent.py               # Core ReAct agent engine, Grok CLI loop & thought parser
├── web_ui.py              # FastAPI Web Cockpit UI with Grok modes, sparks & xterm terminal
├── .env                   # Active environment configuration
├── MEMORY.md              # Long-term persistent preferences & notes
├── requirements.txt       # Dependencies
├── docker/
│   └── Dockerfile.guest_os # Dedicated Debian 12 containerized Micro-OS for agents
├── prompts/
│   ├── system.md          # aZoth-local persona & tool guidance
│   └── modes.py           # Grok persona modes (Regular, Fun, Think, Coder)
├── tools/
│   ├── vm_manager.py      # Guest OS virtual environment orchestrator (Docker/Podman/KVM)
│   ├── terminal_bridge.py # WebSocket PTY terminal bridge for browser interactive shell
│   ├── deep_search.py     # Multi-source DeepSearch with citations
│   ├── x_intelligence.py  # Live X / Twitter search & trend scouting
│   ├── code_runner.py     # Sandbox Python code interpreter
│   ├── browser.py         # Playwright persistent Chrome sandbox engine
│   ├── duckyscript.py     # DuckyScript macro interpreter & engine
│   ├── search.py          # Resilient multi-engine web search (DDG + Yahoo)
│   ├── workspace.py       # Safe sandbox shell & file operations
│   └── definitions.py     # Function calling schemas & dispatcher
├── static/                # 100% Local offline assets (xterm.js, Tailwind, Highlight.js, Marked)
└── sandbox/
    ├── browser_profile/   # Persistent Chrome cookies, logins & storage
    ├── workspace/         # Shared working directory mapped into /workspace of Guest OS
    └── downloads/         # Browser downloads
```

---

## 🔌 Model Context Protocol (MCP) Integration

`azoth-local-agent` ships with a native **Model Context Protocol (MCP)** JSON-RPC 2.0 stdio server. This allows Claude Desktop, Cursor, Hermes Agent, OpenCode, and AGY to connect directly and invoke AZOTH's sandboxed browser, workspace shell, Python interpreter, X intelligence, and Linux VM guest operations without cloud dependencies.

### Claude Desktop / Cursor Configuration

Add to your `claude_desktop_config.json` or Cursor MCP settings:

```json
{
  "mcpServers": {
    "azoth": {
      "command": "python3",
      "args": [
        "/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/azoth-local-agent/agent.py",
        "--mcp"
      ]
    }
  }
}
```

### Exposed MCP Tools

- `azoth_agent_query`: Autonomous Archon meta-tool that executes end-to-end tasks with local/cloud engines.
- `azoth_duckyscript`: Execute human-like macro payloads against browser or desktop.
- `azoth_browser_navigate`: Navigate authenticated persistent Chrome sandbox.
- `azoth_browser_extract`: Extract live text content and interactive inputs from webpage.
- `azoth_browser_screenshot`: Capture full/viewport screenshots.
- `azoth_python_repl`: Safe Python execution in isolated workspace.
- `azoth_shell`: Execute shell commands inside `sandbox/workspace/`.
- `azoth_deep_search`: Multi-source parallel search with verified citations.
- `azoth_x_search` / `azoth_x_trends`: Live X/Twitter intelligence and trend scouting.
- `azoth_vm_exec` / `azoth_vm_status`: Linux Guest OS container/VM inspection and execution.

---

## 🤖 Headless & AI Agent Scripting

Execute single queries directly from the command line or bash scripts:

```bash
# Direct task resolution with local Ollama
python3 agent.py --query "Summarize the files in sandbox/workspace"

# Machine-readable JSON output for agent pipelines
python3 agent.py --query "Check system status" --json

# Run with a specific engine
python3 agent.py --engine hermes --query "Refactor tests/test_mcp.py"
```

---

## 🧪 Testing

Run the test suite:

```bash
# Run MCP protocol tests
python3 -m pytest tests/test_mcp.py -v

# Run all Grok intelligence tests
python3 -m pytest tests/test_grok_intelligence.py -v

# Run full core test suite (68 tests)
python3 -m pytest tests/test_mcp.py tests/test_duckyscript.py tests/test_grok_intelligence.py tests/test_live_routing.py tests/test_manager.py tests/test_vm_os.py -v
```

---

## 🛡️ Sovereign Invariants

- **Zero-Egress by Default**: Operates completely local-first with Ollama or local container guest OS. No telemetry, no third-party phone-home.
- **Sandboxed Execution**: Shell commands and Python interpreter operate in strictly constrained paths (`sandbox/workspace/`).
- **Standardized RPC**: Uses official JSON-RPC 2.0 specs over standard stdio for universal AI interoperability.

---

## License

MIT

