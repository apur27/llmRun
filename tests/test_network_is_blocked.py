"""Proves the autouse fixture in `conftest.py` actually blocks the suite from the network.

Not a mock of the block -- a real attempt to construct a socket, asserted to fail. If this
test ever passes without the fixture active, the fixture has stopped doing its job.
"""

import socket

import pytest


def test_constructing_a_real_socket_is_blocked() -> None:
    """A raw `socket.socket()` call raises rather than opening a real connection."""
    with pytest.raises(OSError, match="network access is blocked"):
        socket.socket()


def test_create_connection_is_blocked() -> None:
    """`socket.create_connection`, the path most HTTP clients use, is blocked too."""
    with pytest.raises(OSError, match="network access is blocked"):
        socket.create_connection(("example.com", 443))
