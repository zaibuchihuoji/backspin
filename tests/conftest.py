"""Session-scoped fixtures shared by integration tests."""
from __future__ import annotations

import pytest

from tests.mock_openai_server import start_server


@pytest.fixture(scope="session")
def openai_base_url() -> str:
    pytest.importorskip("openai")
    return start_server()
