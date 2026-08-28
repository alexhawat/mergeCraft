"""#544 — git-over-HTTPS auth must be basic, and it must actually authenticate.

``git_env_for_token`` brokered the GitHub token as ``Authorization: Bearer
<token>``. GitHub's git transport does not accept ``Bearer`` — that is the REST
API form — so every authenticated fetch was rejected with ``remote: invalid
credentials`` and, with ``GIT_TERMINAL_PROMPT=0`` and no ``GIT_ASKPASS``
fallback, died as ``could not read Username``. ``checkout_pr`` never
established review scope in any observed run.

The tests here refuse to pin a header *string*. They stand up a real git remote
over loopback HTTP whose handler models GitHub: it serves the
``git-upload-pack`` ref advertisement only when the request carries HTTP basic
auth for ``x-access-token:<token>``, and answers ``401`` with ``remote: invalid
credentials`` for anything else. A fetch is then driven through the production
path (``_run_authenticated_git`` → ``git_env_for_token`` →
``git_authenticated_argv``). The old ``Bearer`` scheme fails that server; the
basic scheme passes it.

A second failure lives beside the first. Reporting an auth failure as terminal
is what stops the reviewing agent re-running a fetch that cannot start working,
but the marker set matched ``403 forbidden`` — a phrase git does not write. Its
real shape is ``The requested URL returned error: 403``, which is the
*permission* failure a valid token produces when it lacks access, and the one
most in need of the hint. The remote here can now refuse with either status, so
both the challenge path and the permission path are driven end to end rather
than asserted against a string list.
"""

from __future__ import annotations

import base64
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TOKEN = "ghs_testtoken_abcdefghijklmnopqrstuvwxyz"
EXPECTED_CREDENTIAL = f"x-access-token:{TOKEN}"


def _pkt_line(payload: str) -> bytes:
    """Encode *payload* as a git pkt-line (4-byte hex length prefix + data)."""
    raw = payload.encode()
    return f"{len(raw) + 4:04x}".encode() + raw


def _authorized(header: str) -> bool:
    """Model GitHub: basic auth carrying the token as the password, nothing else."""
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(credential, validate=True).decode()
    except (ValueError, UnicodeDecodeError):
        return False
    return decoded == EXPECTED_CREDENTIAL


class _GitHubLikeHandler(BaseHTTPRequestHandler):
    """Serve the ``git-upload-pack`` advertisement behind GitHub-shaped auth."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # BaseHTTPRequestHandler dispatch hook
        server: Any = self.server
        header = self.headers.get("Authorization", "")
        server.seen_auth.append(header)
        if not _authorized(header):
            self._deny(int(getattr(server, "deny_status", 401)))
            return
        parsed = urlparse(self.path)
        if not parsed.path.endswith("/info/refs") or "service=git-upload-pack" not in (
            parsed.query or ""
        ):
            self.send_error(404)
            return
        advertisement = subprocess.run(
            ["git", "upload-pack", "--stateless-rpc", "--advertise-refs", server.repo_dir],
            capture_output=True,
            check=True,
        ).stdout
        body = _pkt_line("# service=git-upload-pack\n") + b"0000" + advertisement
        self.send_response(200)
        self.send_header("Content-Type", "application/x-git-upload-pack-advertisement")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _deny(self, status: int) -> None:
        """Refuse the request the way the modelled remote would.

        ``401`` carries ``WWW-Authenticate`` and GitHub's ``remote:`` body, so
        git treats it as a challenge and dies on the prompt it cannot answer.
        ``403`` carries neither: there is nothing for git to retry, so curl
        surfaces the status verbatim as ``The requested URL returned error:
        403``. The two shapes are why matching only ``403 forbidden`` never
        recognised a permission failure (#544 follow-up).
        """
        if status == 401:
            body = b"remote: invalid credentials\n"
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="GitHub"')
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        """Silence the stdlib access log — pytest output stays readable."""


def _git(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut the host's git config out of the run.

    A developer machine may carry ``credential.helper`` (macOS keychain, the
    VS Code helper). Any of those can answer the remote's ``401`` and mask
    whether ``extraHeader`` authenticated on its own, which is the whole point
    of these tests.
    """
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.delenv("GIT_ASKPASS", raising=False)
    monkeypatch.delenv("SSH_ASKPASS", raising=False)


@pytest.fixture
def git_http_remote(
    request: pytest.FixtureRequest, tmp_path: Path, isolated_git_config: None
) -> Iterator[tuple[str, list[str]]]:
    """Yield the URL of a loopback git remote plus the auth headers it observed.

    Indirect-parametrize with an HTTP status to choose how the remote refuses an
    unauthenticated request; ``401`` (the GitHub-shaped challenge) is the
    default, and ``403`` models a token that authenticated but lacks access.
    """
    deny_status = int(getattr(request, "param", 401))
    source = tmp_path / "source"
    source.mkdir()
    _git(["init", "--initial-branch=main"], cwd=source)
    _git(["config", "user.email", "test@example.com"], cwd=source)
    _git(["config", "user.name", "Test"], cwd=source)
    (source / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=source)
    _git(["commit", "-m", "init"], cwd=source)

    bare = tmp_path / "origin.git"
    _git(["clone", "--bare", str(source), str(bare)], cwd=tmp_path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHubLikeHandler)
    server.repo_dir = str(bare)  # type: ignore[attr-defined]
    server.seen_auth = []  # type: ignore[attr-defined]
    server.deny_status = deny_status  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}/origin.git", server.seen_auth  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def consumer_repo(tmp_path: Path, git_http_remote: tuple[str, list[str]]) -> Path:
    """A checkout whose ``origin`` points at the loopback remote."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["remote", "add", "origin", git_http_remote[0]], cwd=repo)
    return repo


def test_authenticated_fetch_succeeds_against_a_github_shaped_remote(
    consumer_repo: Path, git_http_remote: tuple[str, list[str]]
) -> None:
    """The brokered credential must actually authenticate, not merely be present."""
    from mergecraft.mcp.git import _run_authenticated_git

    url, seen = git_http_remote
    output = _run_authenticated_git(
        ["ls-remote", "--heads", "origin"],
        cwd=str(consumer_repo),
        token=TOKEN,
        trusted_remote_url=url,
    )

    assert "refs/heads/main" in output
    assert seen, "the remote never saw a request"
    assert all(header.lower().startswith("basic ") for header in seen), seen


def test_the_remote_rejects_the_bearer_scheme_the_bug_used(
    consumer_repo: Path, git_http_remote: tuple[str, list[str]]
) -> None:
    """Guard the guard: the old ``Bearer`` header must fail this remote.

    Without this the suite could pass against a fixture that accepts any
    header, and a regression back to ``Bearer`` would go unnoticed. The
    failure reproduced here is the one from the field: the remote answers
    ``401``, git has no ``GIT_ASKPASS`` to fall back to, and the fetch dies on
    ``terminal prompts disabled``.
    """
    from mergecraft.mcp.git import _run_git
    from mergecraft.utils.git_setup import git_env_for_token

    url, seen = git_http_remote
    env = git_env_for_token(TOKEN, remote_url=url)
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {TOKEN}"

    with pytest.raises(RuntimeError) as excinfo:
        _run_git(
            ["ls-remote", "--heads", "origin"],
            cwd=str(consumer_repo),
            env=env,
            remote_url=url,
        )

    assert any(header.lower().startswith("bearer ") for header in seen), seen
    message = str(excinfo.value).lower()
    assert "invalid credentials" in message or "could not read username" in message
    assert "retrying will not help" in message, "auth failures must be reported as terminal"


@pytest.mark.parametrize("git_http_remote", [403], indirect=True)
def test_a_permission_failure_is_reported_as_terminal(
    consumer_repo: Path, git_http_remote: tuple[str, list[str]]
) -> None:
    """A 403 must carry the terminal hint, not read as a generic git error.

    This is the failure a *valid* token produces when it lacks access — no
    ``contents: read``, an unauthorized SSO grant, a fork — and it is the one
    the hint exists for, because no number of retries grants a permission.
    Unlike the 401 case it never reaches the askpass path: the remote sends no
    challenge, so git has nothing to re-ask and curl surfaces the status
    directly. Matching only ``403 forbidden`` never saw this string.
    """
    from mergecraft.mcp.git import _run_authenticated_git

    url, seen = git_http_remote

    with pytest.raises(RuntimeError) as excinfo:
        _run_authenticated_git(
            ["ls-remote", "--heads", "origin"],
            cwd=str(consumer_repo),
            token="ghs_wrong_token_aaaaaaaaaaaaaaaaaaaaaaaa",
            trusted_remote_url=url,
        )

    assert seen, "the remote never saw a request"
    message = str(excinfo.value).lower()
    assert "403" in message, message
    assert "retrying will not help" in message, (
        "a permission failure must be terminal, or the agent re-runs a fetch "
        "that cannot start working"
    )


@pytest.mark.parametrize(
    "stderr",
    [
        pytest.param(
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "The requested URL returned error: 403",
            id="permission-denied-403",
        ),
        pytest.param(
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "The requested URL returned error: 401",
            id="unauthorized-401-without-challenge",
        ),
        pytest.param(
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "The requested URL returned error: 403 Forbidden",
            id="older-curl-appends-the-reason-phrase",
        ),
        pytest.param(
            "remote: Permission to acme/demo.git denied to octocat.\n"
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "The requested URL returned error: 403",
            id="github-permission-body",
        ),
        pytest.param(
            "remote: Write access to repository not granted.\n"
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "The requested URL returned error: 403",
            id="github-write-access-body",
        ),
        pytest.param(
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            id="challenge-with-no-askpass",
        ),
        pytest.param("remote: invalid credentials", id="rejected-credential"),
    ],
)
def test_is_auth_failure_matches_the_forms_git_actually_emits(stderr: str) -> None:
    """Pin the literal shapes, so narrowing the marker set fails loudly.

    Each string here is what git writes to stderr for a credential that cannot
    work. The predicate gates the terminal hint, and a hint that does not fire
    puts the reviewing agent back in the retry loop the marker set exists to
    stop.
    """
    from mergecraft.mcp.git import _is_auth_failure

    assert _is_auth_failure(stderr), stderr


@pytest.mark.parametrize(
    "stderr",
    [
        pytest.param(
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "The requested URL returned error: 500",
            id="server-error-is-retryable",
        ),
        pytest.param(
            "fatal: unable to access 'https://github.com/acme/demo.git/': "
            "Could not resolve host: github.com",
            id="dns-failure-is-retryable",
        ),
        pytest.param("fatal: not a git repository", id="unrelated-git-error"),
    ],
)
def test_is_auth_failure_leaves_retryable_failures_alone(stderr: str) -> None:
    """Guard the guard: a transient failure must stay retryable.

    Calling everything terminal would be as wrong as calling nothing terminal —
    a 500 or a DNS blip resolves itself on the next attempt, and marking it
    terminal would abandon a review that only needed to try again.
    """
    from mergecraft.mcp.git import _is_auth_failure

    assert not _is_auth_failure(stderr), stderr


def test_git_env_for_token_emits_basic_auth_for_the_documented_username() -> None:
    """The header carries the token as the password under ``x-access-token``."""
    from mergecraft.utils.git_setup import git_env_for_token

    env = git_env_for_token(TOKEN, remote_url="https://github.com/acme/demo.git")

    value = env["GIT_CONFIG_VALUE_0"]
    scheme, _, credential = value.removeprefix("Authorization: ").partition(" ")
    assert scheme == "Basic"
    assert base64.b64decode(credential).decode() == EXPECTED_CREDENTIAL
    assert TOKEN not in value, "the raw token must not travel in the header verbatim"
