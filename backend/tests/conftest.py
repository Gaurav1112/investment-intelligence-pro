"""Suite-wide guard: no test may open a non-loopback network connection unless marked ``network`` (opt-in).

Found in the completion-wave review: a new code path (CAS → AMFI ISIN lookup) could have reached the real AMFI
server from an API test without anyone noticing. Loopback stays allowed (browser tests run a local server)."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator

import pytest

_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo
_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1", "testserver", ""}


def _is_loopback(address: object) -> bool:
    host = address[0] if isinstance(address, tuple) and address else address
    if isinstance(host, str):
        if host in ("localhost",):
            return True
        try:
            return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
        except ValueError:
            return False
    return isinstance(address, (str, bytes))  # AF_UNIX paths


class RealNetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_real_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if request.node.get_closest_marker("network") is not None:
        yield
        return

    def guarded_connect(self: socket.socket, address: object) -> None:
        if not _is_loopback(address):
            raise RealNetworkBlocked(f"test attempted a real network connection to {address!r}")
        _real_connect(self, address)  # type: ignore[arg-type]

    def guarded_create(address: tuple[str, int], *args: object, **kwargs: object) -> socket.socket:
        if not _is_loopback(address):
            raise RealNetworkBlocked(f"test attempted a real network connection to {address!r}")
        return _real_create_connection(address, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        name = host.decode() if isinstance(host, bytes) else str(host or "")
        if name not in _LOCAL_NAMES and not _is_loopback((name, 0)):
            raise RealNetworkBlocked(f"test attempted a real DNS lookup of {name!r}")
        return _real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)
    yield
