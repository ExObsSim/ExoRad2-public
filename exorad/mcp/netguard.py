"""Network guard for the ExoRad MCP server and its job children.

ExoRad can reach the network in two places: the SED downloader
(``sourceSpectrum=sed``) and, in older builds, the import-time version check. The
MCP never needs either, so :func:`block_network` makes every attempt to open an
internet connection (``AF_INET`` / ``AF_INET6``) or to resolve a host name raise
:class:`NetworkBlockedError`. Unix-domain sockets stay allowed: ``multiprocessing``
needs them.

Scope and limits
----------------
* The guard patches the ``socket`` module of the process that calls it. The
  stdio server and every job child install it.
* ``ProcessPoolExecutor`` workers started with ``spawn`` (macOS, Windows) or
  ``forkserver`` (Linux from Python 3.14) re-import everything and do **not**
  inherit the patch. With ``n_threads > 1`` the static refusal of
  ``sourceSpectrum=sed`` in the payload rules is the only control inside the pool.
  Workers started with ``fork`` do inherit it.
* It is a backstop against accidents and misconfigured payloads, not a sandbox
  against hostile native code (which can call ``connect(2)`` directly).
* Do not install it in a process that has to serve HTTP/SSE: binding resolves
  ``127.0.0.1`` through ``getaddrinfo``.

Standard library only.
"""

from __future__ import annotations

import socket

__all__ = ["NetworkBlockedError", "block_network", "is_blocked", "unblock_network"]

_MESSAGE = "network access is disabled in the ExoRad MCP"
_INET = {socket.AF_INET, socket.AF_INET6}
_ORIGINALS: dict[str, object] = {}


class NetworkBlockedError(OSError):
    """An internet connection or host lookup was attempted while the guard is on."""

    def __init__(self, what: str = "") -> None:
        suffix = f" ({what})" if what else ""
        super().__init__(f"{_MESSAGE}{suffix}")


def is_blocked() -> bool:
    """True if :func:`block_network` is currently installed."""
    return bool(_ORIGINALS)


def block_network() -> None:
    """Make internet connections and host lookups raise :class:`NetworkBlockedError`.

    Idempotent: a second call does nothing.
    """
    if _ORIGINALS:
        return
    sock_cls = socket.socket
    _ORIGINALS.update(
        connect=sock_cls.connect,
        connect_ex=sock_cls.connect_ex,
        sendto=sock_cls.sendto,
        create_connection=socket.create_connection,
        getaddrinfo=socket.getaddrinfo,
        gethostbyname=socket.gethostbyname,
        gethostbyname_ex=socket.gethostbyname_ex,
    )
    orig_connect = sock_cls.connect
    orig_connect_ex = sock_cls.connect_ex
    orig_sendto = sock_cls.sendto

    def connect(self, address):
        if self.family in _INET:
            raise NetworkBlockedError("connect")
        return orig_connect(self, address)

    def connect_ex(self, address):
        if self.family in _INET:
            raise NetworkBlockedError("connect_ex")
        return orig_connect_ex(self, address)

    def sendto(self, *args):
        if self.family in _INET:
            raise NetworkBlockedError("sendto")
        return orig_sendto(self, *args)

    def create_connection(*_args, **_kwargs):
        raise NetworkBlockedError("create_connection")

    def getaddrinfo(*_args, **_kwargs):
        raise NetworkBlockedError("getaddrinfo")

    def gethostbyname(*_args, **_kwargs):
        raise NetworkBlockedError("gethostbyname")

    sock_cls.connect = connect  # type: ignore[method-assign]
    sock_cls.connect_ex = connect_ex  # type: ignore[method-assign]
    sock_cls.sendto = sendto  # type: ignore[method-assign]
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    socket.gethostbyname_ex = gethostbyname


def unblock_network() -> None:
    """Remove the guard (for tests; the server never calls this)."""
    if not _ORIGINALS:
        return
    sock_cls = socket.socket
    sock_cls.connect = _ORIGINALS["connect"]  # type: ignore[method-assign,assignment]
    sock_cls.connect_ex = _ORIGINALS["connect_ex"]  # type: ignore[method-assign,assignment]
    sock_cls.sendto = _ORIGINALS["sendto"]  # type: ignore[method-assign,assignment]
    socket.create_connection = _ORIGINALS["create_connection"]  # type: ignore[assignment]
    socket.getaddrinfo = _ORIGINALS["getaddrinfo"]  # type: ignore[assignment]
    socket.gethostbyname = _ORIGINALS["gethostbyname"]  # type: ignore[assignment]
    socket.gethostbyname_ex = _ORIGINALS["gethostbyname_ex"]  # type: ignore[assignment]
    _ORIGINALS.clear()
