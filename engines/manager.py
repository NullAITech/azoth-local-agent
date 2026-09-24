"""Engine & Agent Backend Manager for a-bot.

Supports multi-engine routing, streaming CLI execution, subagent environment passing,
automatic fallback routing, and persistent .env configuration management.

Supported Engines:
1. Ollama (Local Offline Tool Calling & API / CLI)
2. Hermes Agent CLI (/home/neo/.local/bin/hermes)
3. AGY (Google Antigravity CLI /home/neo/.local/bin/agy)
4. Codex CLI (/usr/bin/codex & OpenAI API)
5. xAI Grok (CLI & API)
6. Google Gemini (CLI & API)
7. Claude Code (CLI & Anthropic API)
8. OpenAI (GPT-4o, O3, O1)
9. OpenRouter (Multi-Provider: DeepSeek R1/V3, Llama 3.3, etc.)
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = ROOT / "sandbox" / "workspace"
ENV_FILE = ROOT / ".env"

# Load environment on import
load_dotenv(ENV_FILE)


# =====================================================================
# 1. PERSISTENT ENVIRONMENT & ENGINE CONFIG MANAGER
# =====================================================================

class EnvConfigManager:
    """Thread-safe persistent manager for .env key-values and engine configs."""

    _lock = threading.Lock()

    @classmethod
    def get_env_path(cls) -> Path:
        return ENV_FILE

    @classmethod
    def load(cls) -> dict[str, str]:
        """Reload and return all current environment variables from .env."""
        with cls._lock:
            env_path = cls.get_env_path()
            if not env_path.exists():
                return {}
            load_dotenv(env_path, override=True)
            return cls.read_raw_env()

    @classmethod
    def read_raw_env(cls) -> dict[str, str]:
        """Parse key-value pairs directly from .env file without modifying os.environ."""
        env_path = cls.get_env_path()
        if not env_path.exists():
            return {}
        result: dict[str, str] = {}
        try:
            content = env_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k:
                        result[k] = v
        except Exception:
            pass
        return result

    @classmethod
    def get(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get an environment variable value with fallback to default."""
        return os.getenv(key, default)

    @classmethod
    def set(cls, key: str, value: str, persist: bool = True) -> bool:
        """Set an environment variable and optionally persist it to .env."""
        return cls.set_multiple({key: value}, persist=persist)

    @classmethod
    def set_multiple(cls, updates: dict[str, str], persist: bool = True) -> bool:
        """Atomically update multiple key-value pairs in memory and .env file."""
        with cls._lock:
            for k, v in updates.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = str(v)

            if not persist:
                return True

            env_path = cls.get_env_path()
            try:
                existing_lines: list[str] = []
                if env_path.exists():
                    existing_lines = env_path.read_text(encoding="utf-8").splitlines()

                updated_keys = set(updates.keys())
                new_lines: list[str] = []
                handled_keys: set[str] = set()

                for line in existing_lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key = stripped.split("=", 1)[0].strip()
                        if key in updated_keys:
                            val = updates[key]
                            if val is not None:
                                new_lines.append(f"{key}={val}")
                            handled_keys.add(key)
                            continue
                    new_lines.append(line)

                # Append any new keys that weren't in the file
                for k, v in updates.items():
                    if k not in handled_keys and v is not None:
                        new_lines.append(f"{k}={v}")

                # Atomic file write
                tmp_path = env_path.with_suffix(".tmp")
                tmp_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                tmp_path.replace(env_path)

                load_dotenv(env_path, override=True)
                return True
            except Exception as e:
                print(f"[EnvConfigManager] Error writing .env: {e}")
                return False

    @classmethod
    def get_masked_configs(cls) -> dict[str, Any]:
        """Return configs suitable for UI display with masked secrets."""
        raw = cls.read_raw_env()
        # Merge important keys from os.environ
        keys_to_check = [
            "ACTIVE_ENGINE",
            "MODEL",
            "OPENAI_BASE_URL",
            "OLLAMA_HOST",
            "OPENAI_API_KEY",
            "XAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "OPENROUTER_API_KEY",
            "HERMES_PATH",
            "AGY_PATH",
            "CODEX_PATH",
            "GROK_PATH",
            "GEMINI_PATH",
            "CLAUDE_PATH",
            "OLLAMA_PATH",
        ]
        res: dict[str, Any] = {}
        for k in keys_to_check:
            val = os.getenv(k) or raw.get(k, "")
            if "KEY" in k or "SECRET" in k or "TOKEN" in k:
                if val:
                    if len(val) > 8:
                        res[k] = f"{val[:3]}...{val[-4:]}"
                    else:
                        res[k] = "******"
                    res[f"{k}_configured"] = True
                else:
                    res[k] = ""
                    res[f"{k}_configured"] = False
            else:
                res[k] = val
        return res


# =====================================================================
# 2. CLI BINARY DISCOVERY & CACHE
# =====================================================================

def _find_nvm_node_bins(binary_name: str) -> list[str]:
    """Find binaries installed inside NVM node versions."""
    results = []
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.exists():
        for p in nvm_dir.glob(f"*/bin/{binary_name}"):
            if p.is_file() and os.access(p, os.X_OK):
                results.append(str(p))
    return results


def find_cli(name: str, fallback_paths: Optional[list[str]] = None, env_override: Optional[str] = None) -> Optional[str]:
    """Find binary executable with priority:
    1. Explicit environment variable override (e.g. HERMES_PATH)
    2. shutil.which (system PATH)
    3. NVM node bin directories
    4. Fallback search paths
    """
    # 1. Env override
    if env_override:
        override_val = os.getenv(env_override)
        if override_val and os.path.exists(override_val) and os.access(override_val, os.X_OK):
            return override_val

    # 2. System PATH
    which_path = shutil.which(name)
    if which_path:
        return which_path

    # 3. Dynamic NVM paths for node tools
    nvm_matches = _find_nvm_node_bins(name)
    if nvm_matches:
        return nvm_matches[0]

    # 4. Fallback search paths
    paths = fallback_paths or []
    home = Path.home()
    standard_fallbacks = [
        str(home / ".local" / "bin" / name),
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        f"/bin/{name}",
    ]
    all_candidates = paths + [p for p in standard_fallbacks if p not in paths]

    for p in all_candidates:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p

    return None


def discover_all_clis() -> dict[str, Optional[str]]:
    """Scan and return discovered executable paths for all supported CLIs."""
    return {
        "hermes": find_cli("hermes", ["/home/neo/.local/bin/hermes"], env_override="HERMES_PATH"),
        "agy": find_cli("agy", ["/home/neo/.local/bin/agy"], env_override="AGY_PATH"),
        "codex": find_cli("codex", ["/usr/bin/codex", "/home/neo/.local/bin/codex"], env_override="CODEX_PATH"),
        "grok": find_cli("grok", ["/home/neo/.local/bin/grok"], env_override="GROK_PATH"),
        "gemini": find_cli(
            "gemini",
            ["/home/neo/.nvm/versions/node/v22.22.3/bin/gemini", "/home/neo/.local/bin/gemini"],
            env_override="GEMINI_PATH",
        ),
        "claude": find_cli("claude", ["/usr/local/bin/claude", "/home/neo/.local/bin/claude"], env_override="CLAUDE_PATH"),
        "ollama": find_cli("ollama", ["/usr/local/bin/ollama", "/usr/bin/ollama"], env_override="OLLAMA_PATH"),
    }


CLI_PATHS = discover_all_clis()
HERMES_PATH = CLI_PATHS["hermes"]
AGY_PATH = CLI_PATHS["agy"]
CODEX_PATH = CLI_PATHS["codex"]
GROK_PATH = CLI_PATHS["grok"]
GEMINI_PATH = CLI_PATHS["gemini"]
CLAUDE_PATH = CLI_PATHS["claude"]
OLLAMA_PATH = CLI_PATHS["ollama"]


# =====================================================================
# 3. SUBAGENT ENVIRONMENT PREPARATION
# =====================================================================

def build_subagent_env(
    workspace_dir: Optional[Path] = None,
    extra_env: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build a complete, isolated environment dictionary for subagent processes.

    Ensures critical paths (PATH, HOME, PYTHONPATH, CWD, TERM) and API credentials
    are passed cleanly to child processes.
    """
    ws = workspace_dir or WORKSPACE_DIR
    ws.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()

    # Expand PATH to include local user binaries and node environments
    path_entries = env.get("PATH", "").split(os.pathsep)
    preferred_paths = [
        str(Path.home() / ".local" / "bin"),
        "/home/neo/.local/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    # Include NVM node bin paths
    for node_bin in glob.glob(f"{Path.home()}/.nvm/versions/node/*/bin"):
        preferred_paths.append(node_bin)

    for p in reversed(preferred_paths):
        if os.path.isdir(p) and p not in path_entries:
            path_entries.insert(0, p)

    env["PATH"] = os.pathsep.join(path_entries)
    env["HOME"] = str(Path.home())
    env["CWD"] = str(ws)
    env["WORKSPACE_DIR"] = str(ws)
    env["PYTHONPATH"] = f"{ROOT}:{ws}:{env.get('PYTHONPATH', '')}".strip(":")
    env["PYTHONUNBUFFERED"] = "1"
    env["FORCE_COLOR"] = "0"
    env["TERM"] = "xterm-256color"

    if extra_env:
        env.update(extra_env)

    return env


# =====================================================================
# 4. ENGINE REGISTRY & HEALTH CHECKS
# =====================================================================

class EngineRegistry:
    """Manages active engine configurations and available provider discovery."""

    @staticmethod
    def get_ollama_models(timeout: float = 1.5) -> list[str]:
        """Fetch available Ollama models via local HTTP API."""
        try:
            import requests
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            resp = requests.get(f"{host}/api/tags", timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    @classmethod
    def get_available_engines(cls) -> list[dict[str, Any]]:
        """List all supported engines and their dynamic availability status."""
        clis = discover_all_clis()
        ollama_models = cls.get_ollama_models()

        return [
            {
                "id": "ollama",
                "name": "Ollama (Local Offline)",
                "type": "api",
                "available": len(ollama_models) > 0 or clis["ollama"] is not None,
                "models": ollama_models or ["qwen2.5-coder:1.5b", "llama3:latest", "gemma4:12b"],
                "default_model": ollama_models[0] if ollama_models else "qwen2.5-coder:1.5b",
                "badge": "Local / Free",
                "icon": "🦙",
                "description": "Local offline inference via Ollama service or CLI",
                "cli_path": clis["ollama"],
            },
            {
                "id": "hermes",
                "name": "Hermes Agent CLI",
                "type": "cli",
                "available": clis["hermes"] is not None,
                "path": clis["hermes"],
                "badge": "Nous Hermes",
                "icon": "🏛️",
                "description": "Autonomous tool-calling agent CLI by Nous Research",
                "category": "cli",
            },
            {
                "id": "agy",
                "name": "AGY (Antigravity CLI)",
                "type": "cli",
                "available": clis["agy"] is not None,
                "path": clis["agy"],
                "badge": "Google AGY",
                "icon": "🚀",
                "description": "Google Antigravity autonomous developer CLI",
                "category": "cli",
            },
            {
                "id": "codex",
                "name": "Codex CLI",
                "type": "cli",
                "available": clis["codex"] is not None,
                "path": clis["codex"],
                "badge": "OpenAI Codex",
                "icon": "💻",
                "description": "OpenAI Codex non-interactive code execution CLI",
                "category": "cli",
            },
            {
                "id": "grok_cli",
                "name": "Grok CLI",
                "type": "cli",
                "available": clis["grok"] is not None,
                "path": clis["grok"],
                "badge": "xAI Grok CLI",
                "icon": "⚡",
                "description": "xAI Grok terminal coding agent",
                "category": "cli",
            },
            {
                "id": "gemini",
                "name": "Google Gemini (CLI / API)",
                "type": "cli_or_api",
                "available": clis["gemini"] is not None or bool(os.getenv("GEMINI_API_KEY")),
                "path": clis["gemini"],
                "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
                "default_model": "gemini-2.5-flash",
                "badge": "Google Cloud",
                "icon": "♊",
                "description": "Gemini 2.5 multimodal reasoning via CLI or API",
                "category": "hybrid",
            },
            {
                "id": "claude",
                "name": "Claude Code / Anthropic",
                "type": "cli_or_api",
                "available": clis["claude"] is not None or bool(os.getenv("ANTHROPIC_API_KEY")),
                "path": clis["claude"],
                "models": ["claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
                "default_model": "claude-3-7-sonnet-20250219",
                "badge": "Anthropic",
                "icon": "🎭",
                "description": "Claude 3.7 Sonnet hybrid agent & coding suite",
                "category": "hybrid",
            },
            {
                "id": "xai",
                "name": "xAI Grok (API)",
                "type": "api",
                "available": bool(os.getenv("XAI_API_KEY")),
                "models": ["grok-2-latest", "grok-beta", "grok-vision-beta"],
                "default_model": "grok-2-latest",
                "badge": "xAI Cloud",
                "icon": "✨",
                "description": "xAI Grok cloud API with function calling",
                "category": "api",
            },
            {
                "id": "openai",
                "name": "OpenAI (GPT-4o / O3)",
                "type": "api",
                "available": bool(os.getenv("OPENAI_API_KEY")),
                "models": ["gpt-4o", "gpt-4o-mini", "o3-mini", "o1"],
                "default_model": "gpt-4o",
                "badge": "OpenAI Cloud",
                "icon": "🧠",
                "description": "OpenAI flagship models via REST API",
                "category": "api",
            },
            {
                "id": "openrouter",
                "name": "OpenRouter (DeepSeek / Llama)",
                "type": "api",
                "available": bool(os.getenv("OPENROUTER_API_KEY")),
                "models": ["deepseek/deepseek-r1", "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"],
                "default_model": "deepseek/deepseek-chat",
                "badge": "Multi-Model",
                "icon": "🌐",
                "description": "Unified routing to DeepSeek R1/V3, Llama 3.3, and 200+ models",
                "category": "api",
            },
        ]


# =====================================================================
# 5. CLI COMMAND BUILDER
# =====================================================================

def build_cli_command(
    engine_id: str,
    prompt: str,
    model: Optional[str] = None,
    extra_flags: Optional[list[str]] = None,
) -> tuple[Optional[list[str]], Optional[str]]:
    """Construct command-line arguments for running a CLI agent non-interactively.

    Returns:
        (command_list, error_message)
    """
    clis = discover_all_clis()
    path = clis.get(engine_id) or (clis.get("grok") if engine_id == "grok_cli" else None)

    if not path:
        return None, f"CLI binary for '{engine_id}' is not installed or not found in PATH."

    flags = extra_flags or []

    if engine_id == "hermes":
        cmd = [path, "-z", prompt, "--yolo"] + flags
    elif engine_id == "agy":
        cmd = [path, "--dangerously-skip-permissions", "-p", prompt] + flags
    elif engine_id == "codex":
        cmd = [path, "exec", prompt] + flags
    elif engine_id in ("grok", "grok_cli"):
        cmd = [path, "-p", prompt, "--always-approve"] + flags
    elif engine_id == "gemini":
        cmd = [path, "-p", prompt, "--yolo", "--skip-trust"] + flags
    elif engine_id == "claude":
        cmd = [path, "-p", prompt] + flags
    elif engine_id == "ollama":
        target_model = model or os.getenv("MODEL", "qwen2.5-coder:1.5b")
        cmd = [path, "run", target_model, prompt] + flags
    else:
        return None, f"Unsupported CLI engine ID: {engine_id}"

    return cmd, None


# =====================================================================
# 6. STREAMING & BUFFERED CLI EXECUTION
# =====================================================================

@dataclass
class StreamChunk:
    """Unit of streaming output emitted by a CLI or agent engine."""
    engine: str
    text: str
    is_stderr: bool = False
    is_final: bool = False
    returncode: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def execute_cli_agent_stream(
    engine_id: str,
    prompt: str,
    timeout: int = 120,
    workspace_dir: Optional[Path] = None,
    extra_env: Optional[dict[str, str]] = None,
    model: Optional[str] = None,
) -> Generator[StreamChunk, None, dict[str, Any]]:
    """Execute a CLI agent with real-time streaming output generation.

    Yields:
        StreamChunk instances containing incremental output chunks.

    Returns:
        Summary dict containing overall execution result and returncode.
    """
    ws = workspace_dir or WORKSPACE_DIR
    ws.mkdir(parents=True, exist_ok=True)

    cmd, err = build_cli_command(engine_id, prompt, model=model)
    if err or not cmd:
        yield StreamChunk(
            engine=engine_id,
            text=f"[Error] {err}\n",
            is_stderr=True,
            is_final=True,
            returncode=127,
        )
        return {
            "ok": False,
            "engine": engine_id,
            "error": err,
            "output": "",
            "returncode": 127,
        }

    env = build_subagent_env(ws, extra_env)
    accumulated_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ws),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
    except Exception as e:
        error_msg = f"Failed to spawn CLI process '{engine_id}': {e}"
        yield StreamChunk(
            engine=engine_id,
            text=f"[Error] {error_msg}\n",
            is_stderr=True,
            is_final=True,
            returncode=1,
        )
        return {
            "ok": False,
            "engine": engine_id,
            "error": error_msg,
            "output": "",
            "returncode": 1,
        }

    start_time = time.time()
    timed_out = False

    try:
        # Stream lines in real-time
        if proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                accumulated_lines.append(line)
                yield StreamChunk(engine=engine_id, text=line, is_stderr=False, is_final=False)

                if time.time() - start_time > timeout:
                    timed_out = True
                    proc.kill()
                    break

        proc.wait(timeout=max(1, timeout - int(time.time() - start_time)))
        returncode = proc.returncode if not timed_out else 124

    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
        returncode = 124
    except Exception as e:
        proc.kill()
        proc.wait()
        returncode = 1
        accumulated_lines.append(f"\n[Process error: {e}]")

    full_output = "".join(accumulated_lines).strip()

    if timed_out:
        timeout_msg = f"\n[Timeout] {engine_id} execution exceeded {timeout}s limit."
        yield StreamChunk(
            engine=engine_id,
            text=timeout_msg,
            is_stderr=True,
            is_final=True,
            returncode=124,
        )
        return {
            "ok": False,
            "engine": engine_id,
            "error": f"Execution timed out after {timeout} seconds.",
            "output": full_output,
            "returncode": 124,
        }

    is_ok = (returncode == 0)
    yield StreamChunk(
        engine=engine_id,
        text="",
        is_final=True,
        returncode=returncode,
    )

    return {
        "ok": is_ok,
        "engine": engine_id,
        "output": full_output or "Task completed (no console output).",
        "returncode": returncode,
        "error": None if is_ok else f"Process exited with returncode {returncode}",
    }


# =====================================================================
# 7. FALLBACK ROUTING & EXECUTION
# =====================================================================

DEFAULT_FALLBACK_CHAINS: dict[str, list[str]] = {
    "hermes": ["agy", "codex", "gemini", "grok_cli", "ollama", "xai"],
    "agy": ["gemini", "hermes", "codex", "grok_cli", "ollama", "xai"],
    "codex": ["hermes", "agy", "gemini", "grok_cli", "openai", "ollama"],
    "grok_cli": ["xai", "hermes", "agy", "codex", "gemini", "ollama"],
    "gemini": ["agy", "hermes", "codex", "grok_cli", "ollama", "openrouter"],
    "claude": ["gemini", "agy", "hermes", "codex", "ollama"],
    "ollama": ["xai", "gemini", "openai", "openrouter"],
    "xai": ["ollama", "gemini", "openai", "openrouter"],
    "openai": ["openrouter", "gemini", "xai", "ollama"],
    "anthropic": ["gemini", "openrouter", "openai", "xai", "ollama"],
    "openrouter": ["ollama", "gemini", "xai", "openai"],
}


def get_fallback_candidates(engine_id: str) -> list[str]:
    """Return ordered list of available alternative engines for fallback."""
    chain = DEFAULT_FALLBACK_CHAINS.get(engine_id, ["ollama", "xai", "gemini"])
    available_engines = {e["id"]: e for e in EngineRegistry.get_available_engines() if e["available"]}
    return [cand for cand in chain if cand in available_engines and cand != engine_id]


def execute_cli_agent(
    engine_id: str,
    prompt: str,
    timeout: int = 120,
    workspace_dir: Optional[Path] = None,
    extra_env: Optional[dict[str, str]] = None,
    on_chunk: Optional[Callable[[str], None]] = None,
    auto_fallback: bool = True,
    fallback_chain: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Execute a CLI agent with streaming capture and automatic fallback routing.

    Args:
        engine_id: Primary engine to run (e.g. 'hermes', 'agy', 'codex', 'grok_cli', 'gemini')
        prompt: Task prompt to delegate
        timeout: Execution timeout in seconds
        workspace_dir: Working directory for execution
        extra_env: Environment variables to inject
        on_chunk: Optional callback invoked for each line of output
        auto_fallback: Whether to attempt fallback if primary engine fails
        fallback_chain: Optional custom fallback candidates list
    """
    stream = execute_cli_agent_stream(
        engine_id=engine_id,
        prompt=prompt,
        timeout=timeout,
        workspace_dir=workspace_dir,
        extra_env=extra_env,
    )

    chunks: list[str] = []
    try:
        while True:
            try:
                chunk = next(stream)
                if chunk.text:
                    chunks.append(chunk.text)
                    if on_chunk:
                        on_chunk(chunk.text)
            except StopIteration as stop:
                res = stop.value
                break
    except Exception as e:
        res = {"ok": False, "engine": engine_id, "error": str(e), "output": "".join(chunks), "returncode": 1}

    # If successful or fallback disabled, return directly
    if res.get("ok") or not auto_fallback:
        return res

    # Primary failed -> Attempt fallback routing
    candidates = fallback_chain if fallback_chain is not None else get_fallback_candidates(engine_id)
    attempt_history = [{"engine": engine_id, "error": res.get("error") or "Non-zero exit code"}]

    for fb_engine in candidates:
        if on_chunk:
            on_chunk(f"\n[Router] ⚠️ '{engine_id}' failed. Attempting fallback -> '{fb_engine}'...\n")

        fb_stream = execute_cli_agent_stream(
            engine_id=fb_engine,
            prompt=prompt,
            timeout=timeout,
            workspace_dir=workspace_dir,
            extra_env=extra_env,
        )

        fb_chunks: list[str] = []
        try:
            while True:
                try:
                    fb_chunk = next(fb_stream)
                    if fb_chunk.text:
                        fb_chunks.append(fb_chunk.text)
                        if on_chunk:
                            on_chunk(fb_chunk.text)
                except StopIteration as stop:
                    fb_res = stop.value
                    break
        except Exception as fb_err:
            fb_res = {"ok": False, "engine": fb_engine, "error": str(fb_err), "output": "".join(fb_chunks), "returncode": 1}

        if fb_res.get("ok"):
            fb_res["fallback_used"] = fb_engine
            fb_res["primary_engine"] = engine_id
            fb_res["attempt_history"] = attempt_history
            return fb_res

        attempt_history.append({"engine": fb_engine, "error": fb_res.get("error") or "Execution failed"})

    return {
        "ok": False,
        "engine": engine_id,
        "error": f"Primary engine '{engine_id}' and all fallbacks ({', '.join(candidates)}) failed.",
        "attempt_history": attempt_history,
        "suggested_alternatives": candidates,
        "output": "".join(chunks),
    }
