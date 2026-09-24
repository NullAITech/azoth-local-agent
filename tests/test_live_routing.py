"""Integration verification test for live multi-engine CLI routing & fallback."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.manager import (
    EngineRegistry,
    EnvConfigManager,
    discover_all_clis,
    execute_cli_agent,
    execute_cli_agent_stream,
)


def test_discovered_tools():
    clis = discover_all_clis()
    print("\n--- Discovered CLI Tools ---")
    for name, path in clis.items():
        status = f"✔ Found: {path}" if path else "❌ Not installed"
        print(f"  {name:10} -> {status}")


def test_streaming_callback():
    print("\n--- Testing Streaming Execution Engine ---")
    chunks_received = []

    def handle_chunk(text: str):
        chunks_received.append(text)
        sys.stdout.write(f"[Stream] {text}")
        sys.stdout.flush()

    # Dry-run with gemini or hermes help/test command
    clis = discover_all_clis()
    target_engine = None
    for eng in ["gemini", "hermes", "agy", "codex", "grok_cli"]:
        if clis.get(eng) or (eng == "grok_cli" and clis.get("grok")):
            target_engine = eng
            break

    if not target_engine:
        print("No CLI available for live streaming test, skipping live process test.")
        return

    print(f"Testing streaming on discovered CLI: {target_engine}")
    res = execute_cli_agent(
        engine_id=target_engine,
        prompt="Reply with exactly: 'AZOTH_ROUTER_ONLINE'",
        timeout=15,
        on_chunk=handle_chunk,
        auto_fallback=True,
    )
    print(f"\nExecution result: ok={res.get('ok')}, returncode={res.get('returncode')}")
    print(f"Total chunks captured: {len(chunks_received)}")


def test_fallback_routing_live():
    print("\n--- Testing Live Fallback Routing ---")
    events = []

    def log_event(text: str):
        events.append(text)
        print(f"  [Router Log] {text.strip()}")

    # Request a non-existent CLI engine and verify router automatically picks fallback
    res = execute_cli_agent(
        engine_id="non_existent_engine_999",
        prompt="echo test",
        timeout=10,
        on_chunk=log_event,
        auto_fallback=True,
        fallback_chain=["hermes", "gemini", "agy"],
    )

    print(f"Fallback outcome: ok={res.get('ok')}, used={res.get('fallback_used')}")
    if res.get("fallback_used"):
        print(f"✔ Router successfully recovered using fallback: {res['fallback_used']}")


def test_env_persistence():
    print("\n--- Testing EnvConfigManager Persistence ---")
    configs = EnvConfigManager.get_masked_configs()
    print(f"Configured keys in active .env:")
    for k, v in configs.items():
        if not k.endswith("_configured") and v:
            print(f"  {k:20} = {v}")


if __name__ == "__main__":
    test_discovered_tools()
    test_env_persistence()
    test_streaming_callback()
    test_fallback_routing_live()
