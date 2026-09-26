"""Unit and integration tests for aZoth-local MCP (Model Context Protocol) server."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp_server import mcp_tool_definitions

ROOT = Path(__file__).resolve().parent.parent


def test_mcp_tool_definitions():
    tools = mcp_tool_definitions()
    assert isinstance(tools, list)
    assert len(tools) >= 5

    names = [t["name"] for t in tools]
    assert "azoth_agent_query" in names
    assert any("python" in n or "code" in n for n in names)

    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t
        assert t["inputSchema"].get("type") == "object"


def test_mcp_stdio_server_lifecycle():
    """Verify MCP JSON-RPC protocol over stdin/stdout."""
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "agent.py"), "--mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # 1. Initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test-client", "version": "1.0.0"}},
        }
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()

        resp_line = proc.stdout.readline()
        resp = json.loads(resp_line)
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "azoth-local-agent"
        assert "tools" in resp["result"]["capabilities"]

        # 2. Ping
        ping_req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        proc.stdin.write(json.dumps(ping_req) + "\n")
        proc.stdin.flush()

        ping_resp = json.loads(proc.stdout.readline())
        assert ping_resp["id"] == 2
        assert "result" in ping_resp

        # 3. tools/list
        list_req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
        proc.stdin.write(json.dumps(list_req) + "\n")
        proc.stdin.flush()

        list_resp = json.loads(proc.stdout.readline())
        assert list_resp["id"] == 3
        tools = list_resp["result"]["tools"]
        assert len(tools) >= 5

        # 4. tools/call - execute safe python code in workspace
        call_req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "azoth_python_repl",
                "arguments": {"code": "print(21 * 2)"},
            },
        }
        proc.stdin.write(json.dumps(call_req) + "\n")
        proc.stdin.flush()

        call_resp = json.loads(proc.stdout.readline())
        assert call_resp["id"] == 4
        content = call_resp["result"]["content"]
        assert len(content) > 0
        parsed_out = json.loads(content[0]["text"])
        assert parsed_out.get("ok") is True
        assert "42" in parsed_out.get("output", "")

    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)
