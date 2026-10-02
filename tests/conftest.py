import os
import sys
from pathlib import Path
import pytest

# Ensure headless browser during automated test suites
os.environ.setdefault("BROWSER_HEADLESS", "1")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.browser import get_browser


@pytest.fixture(scope="session")
def browser():
    """Shared browser fixture for browser tests."""
    b = get_browser()
    yield b
