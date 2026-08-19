"""Shared fixtures: block real network access for the whole suite.

The gate claims to run "with no API key and no network." Per-test SDK mocking makes that
true today, but a future test that forgets the mock would silently make a real, billed call
while the gate kept passing. This autouse fixture makes "no network" a mechanical property of
the suite rather than a convention every new test has to remember.
"""

import socket
from collections.abc import Iterator

import pytest


def _deny_network(*_args: object, **_kwargs: object) -> socket.socket:
    """Refuse to construct a real socket or open a real connection."""
    raise OSError(
        "network access is blocked during tests -- mock the client boundary "
        "(e.g. the anthropic SDK's messages.create) instead of reaching a real socket"
    )


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch `socket.socket`/`socket.create_connection` for every test, no opt-in required."""
    monkeypatch.setattr(socket, "socket", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    yield
