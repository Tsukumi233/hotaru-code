from collections.abc import Iterator

import pytest

from hotaru.core.bus import Bus
from hotaru.storage import Storage


@pytest.fixture(autouse=True)
def bus_context() -> Iterator[None]:
    token = Bus.provide(Bus())
    try:
        yield
    finally:
        Bus.restore(token)


@pytest.fixture(autouse=True)
def _storage_teardown() -> Iterator[None]:
    yield
    Storage.reset()
