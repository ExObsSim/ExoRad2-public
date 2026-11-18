"""Tests for the network guard (hazard H6)."""

from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from exorad.mcp import netguard
from exorad.mcp.netguard import NetworkBlockedError, block_network, unblock_network

NETGUARD = Path(netguard.__file__)


@pytest.fixture
def guarded():
    block_network()
    try:
        yield
    finally:
        unblock_network()


@pytest.fixture
def listener():
    """A local TCP listener: a connection to it would succeed if not blocked."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    accepted = []

    def accept():
        try:
            while True:
                conn, _ = server.accept()
                accepted.append(conn)
        except OSError:
            return

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname(), accepted
    server.close()
    thread.join(timeout=2)
    for conn in accepted:
        conn.close()


def test_connect_is_blocked(guarded, listener) -> None:
    address, accepted = listener
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with sock, pytest.raises(NetworkBlockedError, match="network access is disabled"):
        sock.connect(address)
    assert accepted == []


def test_connect_ex_is_blocked(guarded, listener) -> None:
    address, _ = listener
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkBlockedError),
    ):
        sock.connect_ex(address)


def test_ipv6_connect_is_blocked(guarded) -> None:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("no IPv6")
    with sock, pytest.raises(NetworkBlockedError):
        sock.connect(("::1", 9))


def test_create_connection_is_blocked(guarded, listener) -> None:
    address, accepted = listener
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(address, timeout=1)
    assert accepted == []


def test_getaddrinfo_is_blocked(guarded) -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyname("example.com")


def test_udp_sendto_is_blocked(guarded) -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(NetworkBlockedError),
    ):
        sock.sendto(b"x", ("127.0.0.1", 9))


def test_error_is_an_oserror(guarded) -> None:
    assert issubclass(NetworkBlockedError, OSError)
    with pytest.raises(OSError, match="ExoRad MCP"):
        socket.getaddrinfo("example.com", 80)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no unix sockets")
def test_unix_sockets_stay_allowed(
    guarded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # multiprocessing connects over AF_UNIX (relative name: tmp paths are too long)
    monkeypatch.chdir(tmp_path)
    path = "s"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(path)
        conn, _ = server.accept()
        conn.close()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        assert client.connect_ex(path) == 0
    server.close()
    a, b = socket.socketpair()
    a.close()
    b.close()


def test_block_is_idempotent_and_reversible(listener) -> None:
    address, _ = listener
    assert not netguard.is_blocked()
    block_network()
    block_network()  # second call must not wrap the already wrapped functions
    try:
        assert netguard.is_blocked()
    finally:
        unblock_network()
    assert not netguard.is_blocked()
    # fully restored: a real connection works again
    with socket.create_connection(address, timeout=2):
        pass
    unblock_network()  # harmless when not installed


def test_unblocked_by_default(listener) -> None:
    address, _ = listener
    with socket.create_connection(address, timeout=2):
        pass


def test_guard_in_a_fresh_interpreter(tmp_path: Path) -> None:
    """The module is stdlib-only: load it by path, as a job child would."""
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import importlib.util, socket, sys
            spec = importlib.util.spec_from_file_location("ng", {str(NETGUARD)!r})
            ng = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ng)
            srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
            addr = srv.getsockname()
            ng.block_network()
            try:
                socket.create_connection(addr, timeout=1)
            except ng.NetworkBlockedError as exc:
                print("BLOCKED", exc)
                sys.exit(0)
            print("CONNECTED")
            sys.exit(1)
            """
        ),
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-I", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "BLOCKED" in done.stdout


def test_module_is_standard_library_only() -> None:
    source = NETGUARD.read_text(encoding="utf-8")
    imports = [ln for ln in source.splitlines() if ln.startswith(("import ", "from "))]
    assert imports == ["from __future__ import annotations", "import socket"]


def test_documented_limit_about_pool_workers() -> None:
    # the docstring is the contract other tasks read; keep the caveat in it
    doc = netguard.__doc__ or ""
    assert "spawn" in doc
    assert "forkserver" in doc
    assert "n_threads > 1" in doc
