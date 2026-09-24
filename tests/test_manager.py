"""Unit and integration tests for a-bot Multi-Engine Manager & Router."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engines.manager import (
    DEFAULT_FALLBACK_CHAINS,
    EngineRegistry,
    EnvConfigManager,
    StreamChunk,
    build_cli_command,
    build_subagent_env,
    discover_all_clis,
    execute_cli_agent,
    execute_cli_agent_stream,
    find_cli,
    get_fallback_candidates,
)


class TestCliDiscovery:
    """Test CLI binary discovery and fallback paths."""

    def test_find_cli_with_env_override(self, tmp_path):
        fake_bin = tmp_path / "hermes_custom"
        fake_bin.write_text("#!/bin/sh\necho fake hermes\n")
        fake_bin.chmod(0o755)

        with patch.dict(os.environ, {"CUSTOM_HERMES_BIN": str(fake_bin)}):
            found = find_cli("hermes", env_override="CUSTOM_HERMES_BIN")
            assert found == str(fake_bin)

    def test_find_cli_with_fallback_list(self, tmp_path):
        fake_bin = tmp_path / "test_agy"
        fake_bin.write_text("#!/bin/sh\necho agy\n")
        fake_bin.chmod(0o755)

        found = find_cli("non_existent_cmd_xyz", fallback_paths=[str(fake_bin)])
        assert found == str(fake_bin)

    def test_discover_all_clis(self):
        clis = discover_all_clis()
        assert isinstance(clis, dict)
        for key in ["hermes", "agy", "codex", "grok", "gemini", "claude", "ollama"]:
            assert key in clis


class TestSubagentEnvironment:
    """Test environment isolation and variable propagation."""

    def test_build_subagent_env(self, tmp_path):
        ws = tmp_path / "custom_ws"
        env = build_subagent_env(workspace_dir=ws, extra_env={"TEST_EXTRA": "12345"})

        assert "PATH" in env
        assert "/home/neo/.local/bin" in env["PATH"] or str(Path.home() / ".local/bin") in env["PATH"]
        assert env["HOME"] == str(Path.home())
        assert env["CWD"] == str(ws)
        assert env["WORKSPACE_DIR"] == str(ws)
        assert env["PYTHONUNBUFFERED"] == "1"
        assert env["TERM"] == "xterm-256color"
        assert env["TEST_EXTRA"] == "12345"


class TestCommandBuilder:
    """Test CLI command line construction for various engines."""

    @patch("engines.manager.discover_all_clis")
    def test_build_cli_command_hermes(self, mock_discover):
        mock_discover.return_value = {"hermes": "/bin/hermes"}
        cmd, err = build_cli_command("hermes", "list files")
        assert err is None
        assert cmd == ["/bin/hermes", "-z", "list files", "--yolo"]

    @patch("engines.manager.discover_all_clis")
    def test_build_cli_command_agy(self, mock_discover):
        mock_discover.return_value = {"agy": "/bin/agy"}
        cmd, err = build_cli_command("agy", "build app")
        assert err is None
        assert cmd == ["/bin/agy", "--dangerously-skip-permissions", "-p", "build app"]

    @patch("engines.manager.discover_all_clis")
    def test_build_cli_command_codex(self, mock_discover):
        mock_discover.return_value = {"codex": "/bin/codex"}
        cmd, err = build_cli_command("codex", "refactor code")
        assert err is None
        assert cmd == ["/bin/codex", "exec", "refactor code"]

    @patch("engines.manager.discover_all_clis")
    def test_build_cli_command_grok(self, mock_discover):
        mock_discover.return_value = {"grok": "/bin/grok"}
        cmd, err = build_cli_command("grok_cli", "analyze data")
        assert err is None
        assert cmd == ["/bin/grok", "-p", "analyze data", "--always-approve"]

    @patch("engines.manager.discover_all_clis")
    def test_build_cli_command_gemini(self, mock_discover):
        mock_discover.return_value = {"gemini": "/bin/gemini"}
        cmd, err = build_cli_command("gemini", "summarize")
        assert err is None
        assert cmd == ["/bin/gemini", "-p", "summarize", "--yolo", "--skip-trust"]

    @patch("engines.manager.discover_all_clis")
    def test_build_cli_command_missing(self, mock_discover):
        mock_discover.return_value = {"hermes": None}
        cmd, err = build_cli_command("hermes", "prompt")
        assert cmd is None
        assert "not installed" in err


class TestEnvConfigManager:
    """Test persistent .env configuration manager."""

    def test_env_config_read_write(self, tmp_path, monkeypatch):
        test_env_file = tmp_path / ".env.test"
        test_env_file.write_text("# Initial Comment\nMODEL=test-model\n")

        monkeypatch.setattr(EnvConfigManager, "get_env_path", classmethod(lambda cls: test_env_file))

        # Test Read
        raw = EnvConfigManager.read_raw_env()
        assert raw.get("MODEL") == "test-model"

        # Test Set Single
        success = EnvConfigManager.set("XAI_API_KEY", "xai-test-key-12345", persist=True)
        assert success is True
        assert os.getenv("XAI_API_KEY") == "xai-test-key-12345"

        # Test Set Multiple
        success = EnvConfigManager.set_multiple({
            "OPENAI_API_KEY": "sk-test-open-key-9999",
            "ACTIVE_ENGINE": "gemini",
        }, persist=True)
        assert success is True
        assert os.getenv("ACTIVE_ENGINE") == "gemini"

        # Test Masking
        masked = EnvConfigManager.get_masked_configs()
        assert masked["XAI_API_KEY"].startswith("xai...")
        assert masked["XAI_API_KEY_configured"] is True
        assert masked["ACTIVE_ENGINE"] == "gemini"

        # Verify comments preserved in file
        content = test_env_file.read_text(encoding="utf-8")
        assert "# Initial Comment" in content
        assert "ACTIVE_ENGINE=gemini" in content


class TestStreamingAndFallbackExecution:
    """Test streaming output capture and fallback routing."""

    def test_streaming_execution_with_mock_script(self, tmp_path):
        # Create a mock executable that streams two lines
        mock_script = tmp_path / "mock_cli"
        mock_script.write_text(
            "#!/bin/sh\n"
            "echo 'Line 1: Starting'\n"
            "echo 'Line 2: Working on task'\n"
            "echo 'Line 3: Finished'\n"
        )
        mock_script.chmod(0o755)

        with patch("engines.manager.build_cli_command", return_value=([str(mock_script)], None)):
            stream = execute_cli_agent_stream(
                engine_id="hermes",
                prompt="test prompt",
                workspace_dir=tmp_path,
            )

            chunks = []
            final_res = None
            for chunk in stream:
                if chunk.text:
                    chunks.append(chunk.text)
                if chunk.is_final:
                    final_res = chunk

            assert len(chunks) == 3
            assert "Line 1: Starting\n" in chunks
            assert "Line 2: Working on task\n" in chunks
            assert "Line 3: Finished\n" in chunks
            assert final_res.returncode == 0

    def test_execute_cli_agent_fallback_chain(self, tmp_path):
        # Primary fails, fallback succeeds
        failing_script = tmp_path / "failing_cli"
        failing_script.write_text("#!/bin/sh\necho 'Error: missing auth' >&2\nexit 1\n")
        failing_script.chmod(0o755)

        success_script = tmp_path / "success_cli"
        success_script.write_text("#!/bin/sh\necho 'Fallback Success Output'\nexit 0\n")
        success_script.chmod(0o755)

        def mock_builder(engine_id, prompt, model=None, extra_flags=None):
            if engine_id == "hermes":
                return [str(failing_script)], None
            elif engine_id == "agy":
                return [str(success_script)], None
            return None, "Not found"

        with patch("engines.manager.build_cli_command", side_effect=mock_builder):
            captured_chunks = []
            res = execute_cli_agent(
                engine_id="hermes",
                prompt="test fallback",
                workspace_dir=tmp_path,
                on_chunk=lambda c: captured_chunks.append(c),
                auto_fallback=True,
                fallback_chain=["agy"],
            )

            assert res.get("ok") is True
            assert res.get("fallback_used") == "agy"
            assert res.get("primary_engine") == "hermes"
            assert "Fallback Success Output" in res.get("output")
            assert any("Attempting fallback" in c for c in captured_chunks)

    def test_engine_registry_listing(self):
        engines = EngineRegistry.get_available_engines()
        assert len(engines) >= 7
        engine_ids = [e["id"] for e in engines]
        assert "ollama" in engine_ids
        assert "hermes" in engine_ids
        assert "agy" in engine_ids
        assert "codex" in engine_ids
        assert "grok_cli" in engine_ids
        assert "gemini" in engine_ids
