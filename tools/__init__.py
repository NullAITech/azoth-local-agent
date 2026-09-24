"""Tools package for a-bot."""

from .definitions import AGENT_TOOLS, execute_tool
from .browser import get_browser
from .duckyscript import run_duckyscript, get_ducky_engine
from .workspace import resolve_safe_path, WORKSPACE_DIR
from .search import search_web, fetch_page

__all__ = [
    "AGENT_TOOLS",
    "execute_tool",
    "get_browser",
    "run_duckyscript",
    "get_ducky_engine",
    "resolve_safe_path",
    "WORKSPACE_DIR",
    "search_web",
    "fetch_page",
]
