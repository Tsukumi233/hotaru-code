from collections.abc import Iterator

import pytest

from hotaru.core.bus import Bus


@pytest.fixture(autouse=True)
def bus_context() -> Iterator[None]:
    token = Bus.provide(Bus())
    try:
        yield
    finally:
        Bus.restore(token)
