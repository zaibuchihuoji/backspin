"""Session-scoped fixtures shared by integration tests."""
from __future__ import annotations

import pytest

from tests.mock_anthropic_server import start_anthropic_server
from tests.mock_openai_server import start_server


@pytest.fixture(scope="session")
def mock_openai_origin() -> str:
    """Raw origin (no /v1) of the mock OpenAI API — for proxy upstreams."""
    pytest.importorskip("openai")
    return start_server().rsplit("/v1", 1)[0]


@pytest.fixture(scope="session")
def openai_base_url(mock_openai_origin) -> str:
    return mock_openai_origin + "/v1"


@pytest.fixture(scope="session")
def anthropic_origin() -> str:
    pytest.importorskip("anthropic")
    return start_anthropic_server()
