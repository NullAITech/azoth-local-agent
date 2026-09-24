"""
Tests for aZoth Linux Guest OS & Virtual Environment Subsystem
Verifies container/sandbox isolation, command execution, vitals reporting, and tool dispatching.
"""

import pytest
from tools.vm_manager import guest_os
from tools.definitions import AGENT_TOOLS, execute_tool


def test_vm_status_and_backend():
    """Verify Guest OS status reports active backend and environment info."""
    status = guest_os.get_status()
    assert isinstance(status, dict)
    assert "backend" in status
    assert status["backend"] in ("docker", "podman", "local_sandbox")
    assert "running" in status
    assert "workspace_dir" in status


def test_vm_command_execution():
    """Verify command execution inside Guest OS environment."""
    res = guest_os.run_command("echo 'azoth_guest_os_ok' && whoami")
    assert res.get("exit_code") == 0
    assert "azoth_guest_os_ok" in res.get("stdout", "")
    assert res.get("backend") in ("docker", "podman", "local_sandbox")


def test_vm_workspace_filesystem_persistence():
    """Verify that file operations in /workspace reflect in the sandbox workspace directory."""
    test_token = "azoth_test_token_99482"
    # Write file inside guest OS
    write_res = guest_os.run_command(f"echo '{test_token}' > /workspace/vm_test_file.txt")
    assert write_res.get("exit_code") == 0

    # Read back through tool
    read_res = execute_tool("read_file", {"path": "vm_test_file.txt"})
    assert read_res.get("ok") is True
    assert test_token in read_res.get("content", "")

    # Clean up
    guest_os.run_command("rm -f /workspace/vm_test_file.txt")


def test_agent_vm_tools_registered():
    """Verify vm_exec and vm_status tools are in AGENT_TOOLS schema."""
    tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
    assert "vm_exec" in tool_names
    assert "vm_status" in tool_names
    assert "vm_install" in tool_names
    assert "vm_restart" in tool_names


def test_execute_tool_vm_exec():
    """Verify execute_tool correctly dispatches vm_exec."""
    res = execute_tool("vm_exec", {"command": "uname -s"})
    assert res.get("exit_code") == 0
    assert "Linux" in res.get("stdout", "")


def test_execute_tool_vm_status():
    """Verify execute_tool correctly dispatches vm_status."""
    res = execute_tool("vm_status", {})
    assert isinstance(res, dict)
    assert res.get("running") is True
