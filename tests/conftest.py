"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.browser import get_browser


@pytest.fixture(scope="session")
def browser():
    """Shared browser fixture for browser tests."""
    b = get_browser()
    yield b
