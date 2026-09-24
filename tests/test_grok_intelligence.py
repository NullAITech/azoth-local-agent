"""Integration and unit tests for Grok-inspired intelligence features in aZoth-local.

Covers:
- Grok Persona & Reasoning Modes (Truth/Regular, Fun, Think, Coder)
- DeepSearch Multi-Source Parallel Engine & Citations
- Live X (Twitter) Intelligence & Trend Scouting
- Interactive Python Code Interpreter
- Thinking & Chain-of-Thought (<think>...</think>) Extraction
- Web UI Grok Endpoints & Mode Switching
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import build_system_prompt, extract_thinking
from prompts.modes import DEFAULT_MODE, MODES, get_mode, list_modes
from tools.code_runner import run_python
from tools.deep_search import deep_search
from tools.definitions import AGENT_TOOLS, execute_tool
from tools.x_intelligence import draft_x_thread, scout_x_trends, search_x
import web_ui


class TestGrokModes:
    def test_list_all_modes(self):
        modes = list_modes()
        mode_ids = [m["id"] for m in modes]
        assert "regular" in mode_ids
        assert "fun" in mode_ids
        assert "think" in mode_ids
        assert "coder" in mode_ids

    def test_get_mode_valid_and_fallback(self):
        fun = get_mode("fun")
        assert fun.name == "Fun Mode"
        assert "🌶️" in fun.icon
        assert "Witty" in fun.instructions

        fallback = get_mode("non_existent_mode_xyz")
        assert fallback.id == DEFAULT_MODE

    def test_system_prompt_includes_mode_instructions(self):
        prompt_regular = build_system_prompt("regular")
        assert "Truth & Regular Mode" in prompt_regular

        prompt_fun = build_system_prompt("fun")
        assert "Grok Fun Mode" in prompt_fun
        assert "witty" in prompt_fun.lower()

        prompt_think = build_system_prompt("think")
        assert "DeepSearch & Think Mode" in prompt_think
        assert "<think>" in prompt_think

        prompt_coder = build_system_prompt("coder")
        assert "Coder & Builder Mode" in prompt_coder


class TestThinkingParser:
    def test_extract_thinking_present(self):
        raw = "<think>\nStep 1: Check user intent.\nStep 2: Synthesize answer.\n</think>\nHere is the final answer."
        thinking, clean = extract_thinking(raw)
        assert thinking is not None
        assert "Step 1: Check user intent." in thinking
        assert clean == "Here is the final answer."

    def test_extract_thinking_absent(self):
        raw = "Direct answer without chain of thought."
        thinking, clean = extract_thinking(raw)
        assert thinking is None
        assert clean == "Direct answer without chain of thought."


class TestCodeRunner:
    def test_run_python_success(self):
        code = "val = sum([1, 2, 3, 4, 5]); print(f'Sum: {val}')"
        res = run_python(code, timeout_sec=5)
        assert res["ok"] is True
        assert "Sum: 15" in res["stdout"]
        assert res["returncode"] == 0

    def test_run_python_stderr(self):
        code = "raise ValueError('Custom test error')"
        res = run_python(code, timeout_sec=5)
        assert res["ok"] is False
        assert "ValueError: Custom test error" in res["output"]

    def test_run_python_timeout(self):
        code = "import time; time.sleep(5)"
        res = run_python(code, timeout_sec=1)
        assert res["ok"] is False
        assert "timed out" in res["error"].lower()


class TestDeepSearch:
    def test_deep_search_structure_and_citations(self):
        with patch("tools.deep_search.search_web") as mock_search:
            mock_search.return_value = {
                "ok": True,
                "results": [
                    {
                        "title": "xAI Grok Documentation",
                        "url": "https://x.ai/docs/grok",
                        "snippet": "Official docs for Grok API.",
                    },
                    {
                        "title": "Grok AI Benchmark Review",
                        "url": "https://tech-review.io/grok-benchmark",
                        "snippet": "Performance analysis of Grok.",
                    },
                ],
            }
            res = deep_search("xAI Grok", max_sources=2, fetch_top_pages=False)
            assert res["ok"] is True
            assert res["total_sources"] >= 1
            assert "Sources & Citations" in res["bibliography_markdown"]
            assert "[1]" in res["bibliography_markdown"]


class TestXIntelligence:
    def test_search_x_structure(self):
        with patch("tools.x_intelligence.search_web") as mock_search:
            mock_search.return_value = {
                "ok": True,
                "results": [
                    {
                        "title": "Elon Musk on X: Grok 3 launch",
                        "url": "https://x.com/elonmusk/status/123456789",
                        "snippet": "Excited to share Grok 3 today.",
                    }
                ],
            }
            res = search_x("elonmusk grok", max_results=3)
            assert res["ok"] is True
            assert res["count"] == 1
            post = res["posts"][0]
            assert post["handle"] == "@elonmusk"
            assert post["is_status"] is True

    def test_draft_x_thread(self):
        res = draft_x_thread("Building autonomous local AI agents", tone="technical", num_tweets=3)
        assert res["ok"] is True
        assert res["num_tweets"] == 3
        assert "Hook" in res["guidance"]


class TestAgentToolsDispatch:
    def test_new_tools_in_definitions(self):
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "deep_search" in names
        assert "x_search" in names
        assert "x_trends" in names
        assert "x_draft_thread" in names
        assert "python_repl" in names

    def test_execute_python_repl(self):
        res = execute_tool("python_repl", {"code": "print('TOOL_EXEC_OK')"})
        assert res["ok"] is True
        assert "TOOL_EXEC_OK" in res["stdout"]


class TestWebUiEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(web_ui.app)

    def test_modes_endpoints(self, client):
        res = client.get("/api/modes")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert len(data["modes"]) == 4

        # Switch mode to fun
        switch_res = client.post("/api/mode", json={"mode": "fun"})
        assert switch_res.status_code == 200
        assert switch_res.json()["mode"] == "fun"

        # Switch back to regular
        client.post("/api/mode", json={"mode": "regular"})

    def test_python_run_api(self, client):
        res = client.post("/api/python/run", json={"code": "x = 40 + 2; print(f'Ans:{x}')"})
        assert res.status_code == 200
        assert "Ans:42" in res.json()["stdout"]
