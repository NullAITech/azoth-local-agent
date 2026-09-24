"""Engines package for a-bot."""

from .manager import (
    DEFAULT_FALLBACK_CHAINS,
    EnvConfigManager,
    EngineRegistry,
    StreamChunk,
    build_cli_command,
    build_subagent_env,
    discover_all_clis,
    execute_cli_agent,
    execute_cli_agent_stream,
    find_cli,
    get_fallback_candidates,
)

__all__ = [
    "DEFAULT_FALLBACK_CHAINS",
    "EnvConfigManager",
    "EngineRegistry",
    "StreamChunk",
    "build_cli_command",
    "build_subagent_env",
    "discover_all_clis",
    "execute_cli_agent",
    "execute_cli_agent_stream",
    "find_cli",
    "get_fallback_candidates",
]
