#!/usr/bin/env python3
"""Standard Model Context Protocol (MCP) server for aZoth-local Agent.

Exposes AZOTH's autonomous tools (browser automation, sandbox execution,
DeepSearch, X intelligence, and Linux VM guest operations) over stdio
to Claude Desktop, Cursor, Cline, Hermes Agent, and OpenCode.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from tools.definitions import AGENT_TOOLS, execute_tool
from engines.manager import execute_cli_agent


def mcp_tool_definitions() -> list[dict[str, Any]]:
    """Convert OpenAI-style tool definitions to standard MCP tool schemas."""
    mcp_tools = []
    
    # 1. Meta-tool: Full AZOTH Agent Query
    mcp_tools.append({
        "name": "azoth_agent_query",
        "description": "Send a high-level task to the autonomous aZoth Archon agent. Solves tasks using local models or configured CLI engines, returning thinking trace and final output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task or query description for the agent"
                },
                "engine": {
                    "type": "string",
                    "description": "Engine to use: 'ollama' (default local), 'hermes', 'agy', 'codex', 'grok_cli'",
                    "default": "ollama"
                }
            },
            "required": ["prompt"]
        }
    })

    # 2. Map all native AGENT_TOOLS
    for t in AGENT_TOOLS:
        fn = t.get("function", {})
        name = fn.get("name")
        desc = fn.get("description", "")
        params = fn.get("parameters", {"type": "object", "properties": {}})
        
        mcp_tools.append({
            "name": f"azoth_{name}",
            "description": desc,
            "inputSchema": params
        })

    return mcp_tools


def run_mcp_server():
    """Run JSON-RPC 2.0 stdio server loop for Model Context Protocol."""
    tools_list = mcp_tool_definitions()

    def send_response(req_id: Any, result: Any = None, error: dict[str, Any] | None = None):
        payload = {"jsonrpc": "2.0", "id": req_id}
        if error:
            payload["error"] = error
        else:
            payload["result"] = result
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue

        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            send_response(None, None, {"code": -32700, "message": "Parse error"})
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            send_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "azoth-local-agent",
                    "version": "3.0.0"
                }
            })
            continue

        if method == "notifications/initialized":
            continue

        if method == "ping":
            send_response(req_id, {})
            continue

        if method == "tools/list":
            send_response(req_id, {"tools": tools_list})
            continue

        if method == "tools/call":
            tool_name = params.get("name", "")
            args = params.get("arguments", {})

            # Handle Meta-tool
            if tool_name == "azoth_agent_query":
                prompt = args.get("prompt", "")
                engine = args.get("engine", "ollama")
                try:
                    res = execute_cli_agent(engine_id=engine, prompt=prompt, auto_fallback=True)
                    send_response(req_id, {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(res, indent=2, ensure_ascii=False)
                        }]
                    })
                except Exception as e:
                    send_response(req_id, None, {"code": -32000, "message": str(e)})
                continue

            # Strip 'azoth_' prefix to get original tool name
            orig_name = tool_name
            if orig_name.startswith("azoth_"):
                orig_name = orig_name[6:]

            try:
                result = execute_tool(orig_name, args)
                send_response(req_id, {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(result, indent=2, ensure_ascii=False)
                    }]
                })
            except Exception as e:
                send_response(req_id, None, {"code": -32000, "message": f"Tool execution failed: {e}"})
            continue

        send_response(req_id, None, {"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    run_mcp_server()
