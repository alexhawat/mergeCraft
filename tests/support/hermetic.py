"""Hermetic-test guards, registered as a pytest plugin from ``tests/conftest.py``.

Four autouse guards keep unit tests independent of the machine they run on
(audit TST-F1, F5, F6, F21):

* **Network guard** - non-loopback ``connect``/``getaddrinfo`` calls and any
  real ``GitHubClient`` transport raise :class:`NetworkBlockedError`. The
  attempt is also recorded and the test is failed at teardown, so a product
  ``except Exception`` cannot turn an accidental call into a silent pass.
  Opt in per test with ``@pytest.mark.network`` (``integration`` and ``live``
  tests are opted in too). There is no per-file allow-list.
* **Environment scrub** - ``MERGECRAFT_*``, provider keys, ``GITHUB_*``, proxy,
  ``OTEL_*`` and similar variables are removed before each test. A test opts a
  value back in with ``monkeypatch.setenv``. ``live`` tests keep their
  credentials.
* **Home isolation** - ``HOME`` and the XDG directories point at a per-test
  directory outside ``tmp_path``, so nothing lands in ``~/.cache`` or ``~/.config``.
* **Per-test timeout** - ``SIGALRM`` based (no extra dependency). Override with
  ``@pytest.mark.timeout(seconds)``; ``0`` disables it.

A session guard additionally fails the run when tests leave new files under
the checkout's ``.mergecraft`` directory.
"""

from __future__ import annotations

import ipaddress
import os
import signal
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TEST_TIMEOUT_SECONDS = 180

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", ""})
_NETWORK_MARKERS = ("network", "integration", "live")

# Exact variable names and prefixes removed before every test.
# CI is runner metadata: the sandbox capability probe needs it to try sudo unshare.
_SCRUB_EXACT = frozenset(
    {
        "GH_TOKEN",
        "GH_HOST",
        "GH_ENTERPRISE_TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "ANTHROPIC_AUTH_TOKEN",
        "CODEX_HOME",
        "OPENCODE_CONFIG",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "TMPDIR_MERGECRAFT",
    }
)
_SCRUB_PREFIXES = (
    "MERGECRAFT_",
    "GITHUB_",
    "RUNNER_",
    "OTEL_",
    "LOGFIRE_",
    "ANTHROPIC_",
    "OPENAI_",
    "GEMINI_",
    "GOOGLE_",
    "OPENROUTER_",
    "CURSOR_",
    "OPENCODE_",
    "CODEX_",
    "AZURE_OPENAI_",
    "MISTRAL_",
    "GROQ_",
)
_SCRUB_SUFFIXES = ("_API_KEY",)


class NetworkBlockedError(RuntimeError):
    """A unit test tried to reach a non-loopback host."""


_VIOLATIONS: list[str] = []


def _is_loopback_host(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is None:
        return True
    text = str(host)
    if text.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _block(what: str) -> NetworkBlockedError:
    message = (
        f"network access blocked in unit tests: {what}. Use a fake or an "
        "httpx.MockTransport, or mark the test with @pytest.mark.network."
    )
    _VIOLATIONS.append(message)
    return NetworkBlockedError(message)


def _check_address(sock: socket.socket, address: Any) -> None:
    inet = sock.family in (socket.AF_INET, socket.AF_INET6)
    if inet and isinstance(address, tuple) and not _is_loopback_host(address[0]):
        raise _block(f"connect to {address[0]!r}")


def _install_network_guard(mp: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        _check_address(self, address)
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        _check_address(self, address)
        return real_connect_ex(self, address)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback_host(host):
            raise _block(f"DNS lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    mp.setattr(socket.socket, "connect", guarded_connect)
    mp.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    mp.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture
def offline_upstream_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve upstream hosts (SSRF pre-resolve) to a public address without DNS.

    Use with ``pytestmark = pytest.mark.usefixtures("offline_upstream_resolution")``
    for tests that exercise the credential broker or clone path.
    """
    from mergecraft.security import egress

    monkeypatch.setattr(
        egress,
        "_resolve_host_addresses",
        lambda _host: (ipaddress.ip_address("93.184.216.34"),),
    )


@pytest.fixture
def offline_analyzer_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make managed-analyzer binary downloads fail fast and offline.

    Tests that run the analyzer pipeline without caring about the tools see each
    managed binary as unavailable (a ``ProvisionError``) instead of reaching
    the release host. Tests that need the real tools are marked ``integration``
    and ``network`` instead.
    """
    from mergecraft.analyzers import provision

    def _refuse(url: str, dest: object) -> None:
        msg = f"managed analyzer download blocked in offline unit tests: {url}"
        raise provision.ProvisionError(msg)

    monkeypatch.setattr(provision, "_download_pinned_url", _refuse)


def _network_allowed(request: pytest.FixtureRequest) -> bool:
    return any(request.node.get_closest_marker(name) for name in _NETWORK_MARKERS)


@pytest.fixture(autouse=True)
def _block_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Block non-loopback network access (TST-F1); fail the test if it was attempted."""
    if _network_allowed(request):
        yield
        return
    _VIOLATIONS.clear()
    _install_network_guard(monkeypatch)
    yield
    if _VIOLATIONS:
        attempts = "; ".join(sorted(set(_VIOLATIONS)))
        _VIOLATIONS.clear()
        pytest.fail(
            f"test attempted blocked network access (swallowed by product code?): {attempts}"
        )


def _should_scrub(name: str) -> bool:
    return (
        name in _SCRUB_EXACT
        or name.startswith(_SCRUB_PREFIXES)
        or name.endswith(_SCRUB_SUFFIXES)
        or name.endswith("_AUTH_TOKEN")
    )


@pytest.fixture(autouse=True)
def _isolate_environment(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Scrub ambient env and point HOME/XDG at a per-test dir (TST-F5, TST-F6)."""
    if not request.node.get_closest_marker("live"):
        for name in [n for n in os.environ if _should_scrub(n)]:
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    # Default trace sink is cwd-relative (``.mergecraft/traces``); keep it out of the checkout.
    monkeypatch.setenv("MERGECRAFT_TRACE_DIR", str(home / "traces"))


class TestTimeoutError(Exception):
    """A test exceeded its per-test time budget."""

    __test__ = False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """Fail a test that runs longer than its budget (TST-F21)."""
    marker = item.get_closest_marker("timeout")
    seconds = float(marker.args[0]) if marker and marker.args else DEFAULT_TEST_TIMEOUT_SECONDS
    usable = (
        seconds > 0
        and hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )
    if not usable:
        yield
        return

    def on_alarm(signum: int, frame: Any) -> None:
        raise TestTimeoutError(f"test exceeded its {seconds:g}s timeout")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _checkout_state_files() -> set[Path]:
    root = _ROOT / ".mergecraft"
    if not root.is_dir():
        return set()
    return {p for p in root.rglob("*") if p.is_file()}


@pytest.fixture(scope="session", autouse=True)
def _checkout_untouched() -> Iterator[None]:
    """Fail the session when tests create files under the checkout's ``.mergecraft`` (TST-F6)."""
    before = _checkout_state_files()
    yield
    leaked = sorted(_checkout_state_files() - before)
    if leaked:
        listing = "\n  ".join(str(p.relative_to(_ROOT)) for p in leaked)
        pytest.fail(f"tests wrote into the checkout; use tmp_path/monkeypatch.chdir:\n  {listing}")
