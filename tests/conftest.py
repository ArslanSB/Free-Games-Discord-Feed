from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_feed_xml() -> str:
    return (FIXTURES / "sample_feed.xml").read_text()
