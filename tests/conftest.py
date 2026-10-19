import tempfile

import pytest


@pytest.fixture
def app_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d
