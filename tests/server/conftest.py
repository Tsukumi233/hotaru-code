from __future__ import annotations

from collections.abc import Iterator

import pytest

from hotaru.runtime import AppContext
from tests.helpers import create_test_app_context


@pytest.fixture
def app_ctx() -> Iterator[AppContext]:
    with create_test_app_context() as ctx:
        yield ctx
