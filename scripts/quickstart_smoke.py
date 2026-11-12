#!/usr/bin/env python3
"""End-to-end smoke of the README Quickstart against a throwaway GitHub repository.

Drives install -> ``init`` -> ``provider auth`` -> push scaffold -> open PR -> wait for
the mergeCraft review, then asserts a review was actually posted and the review run
concluded. Cleanup (close PR, delete branch, reset ``main``, delete the provider secret)
runs from a separate subcommand so the workflow can invoke it from an ``always()`` step.

The pure parts (argument handling, README install-spec parsing, the "was a review posted"
and "did the run conclude" predicates, the cleanup order, redaction) take plain data so
``tests/ci/test_quickstart_smoke.py`` drives them with fixture API payloads. The functions
that shell out are thin and take an injectable ``runner``.

Secrets: ``SMOKE_REPO_TOKEN`` and ``SMOKE_PROVIDER_API_KEY`` are read from the environment
only. The repo token reaches ``gh``/``git`` as ``GH_TOKEN``; the provider key is piped to
``mergecraft provider auth`` on stdin. Neither appears on a command line or in output.

Module: scripts.quickstart_smoke
Depends: argparse, json, os, re, subprocess, time, urllib (stdlib only)
Exports:
    parse_args, readme_install_spec, review_posted, run_outcome, evaluate, cleanup_plan,
    redact, wait_for_review, main
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_REPO = "alexhawat/mergecraft-smoke"
DEFAULT_PROVIDER = "opencode-go"
DEFAULT_MODEL = "opencode-go/deepseek-v4.1-flash"
REVIEW_WORKFLOW_PATH = ".github/workflows/mergecraft.yml"
REVIEW_BOT_LOGIN = "github-actions[bot]"
BRANCH_PREFIX = "smoke/"
SECRET_PREFIX = "LLM_PROVIDER_"
SUBMITTED_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED"})
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
# Run conclusions that mean the review job ran to the end. ``failure`` is allowed because
# the scaffold can fail its final gate step on a "would not approve" verdict after the
# review was posted; the posted-review predicate is what the acceptance asserts.
CONCLUDED = frozenset({"success", "failure"})

# ``uv tool install mergecraft-action==0.1.0a5`` as written in the README Quickstart.
_INSTALL_RE = re.compile(r"^\s*uv tool install (mergecraft-action==\S+)\s*$", re.MULTILINE)
_SECTION_RE = re.compile(r"^## Quickstart\s*$(.*?)(?=^## )", re.MULTILINE | re.DOTALL)
_TOKEN_RE = re.compile(
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b|\bsk-[A-Za-z0-9_-]{8,}\b"
)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class SmokeError(Exception):
    """A smoke step failed; the message is the operator-facing reason."""


# --------------------------------------------------------------------------- pure parts


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the ``run`` / ``cleanup`` subcommands."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", default=DEFAULT_REPO, help="owner/name of the scratch repo")
        p.add_argument(
            "--expect-repo",
            required=True,
            help="the one repo this command may act on (the workflow's SCRATCH_REPO)",
        )

    run = sub.add_parser("run", help="run one Quickstart scenario and assert the review")
    common(run)
    run.add_argument("--install", choices=("release", "source"), default="release")
    run.add_argument("--source-dir", type=Path, default=Path.cwd(), help="checkout to build")
    run.add_argument("--readme", type=Path, default=Path("README.md"))
    run.add_argument("--version", default="", help="override the README version pin")
    run.add_argument("--provider", default=DEFAULT_PROVIDER)
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    run.add_argument("--timeout", type=float, default=1200.0, help="seconds to wait for review")
    run.add_argument("--poll-interval", type=float, default=20.0)
    run.add_argument("--workdir", type=Path, default=None)

    cleanup = sub.add_parser("cleanup", help="close PRs, delete branches, reset main")
    common(cleanup)

    args = parser.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error(f"--repo must be owner/name, got {args.repo!r}")
    if args.command == "run":
        if args.timeout <= 0 or args.poll_interval <= 0:
            parser.error("--timeout and --poll-interval must be positive")
        if not re.fullmatch(r"[\w.-]+", str(args.run_id)):
            parser.error("--run-id must be a plain token")
    return args


def readme_install_spec(readme_text: str, override: str = "") -> str:
    """Return the ``mergecraft-action==X`` requirement the Quickstart tells users to install."""
    if override.strip():
        return f"mergecraft-action=={override.strip().removeprefix('==')}"
    section = _SECTION_RE.search(readme_text)
    match = _INSTALL_RE.search(section.group(1) if section else "")
    if match is None:
        raise SmokeError(
            "README Quickstart no longer contains a `uv tool install mergecraft-action==...` line"
        )
    return match.group(1)


def branch_name(run_id: str, install: str) -> str:
    return f"{BRANCH_PREFIX}{run_id}-{install}"


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Strip known secret values and token-shaped strings from ``text``."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "<redacted>")
    return _TOKEN_RE.sub("<redacted>", text)


def review_posted(
    reviews: Sequence[Mapping[str, Any]],
    issue_comments: Sequence[Mapping[str, Any]],
    review_comments: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return evidence that the workflow posted a review; empty means none was posted."""

    def by_bot(item: Mapping[str, Any]) -> bool:
        user = item.get("user") or {}
        return isinstance(user, Mapping) and user.get("login") == REVIEW_BOT_LOGIN

    evidence: list[str] = []
    for review in reviews:
        # A PENDING review is an unsubmitted draft, not something a reader can see.
        if by_bot(review) and review.get("state") != "PENDING":
            evidence.append(f"review {review.get('id')} ({review.get('state')})")
    evidence += [f"review comment {c.get('id')}" for c in review_comments if by_bot(c)]
    evidence += [f"issue comment {c.get('id')}" for c in issue_comments if by_bot(c)]
    return evidence


def submitted_review_evidence(reviews: Sequence[Mapping[str, Any]], head_sha: str) -> list[str]:
    """Bot reviews that were submitted (with a body) against ``head_sha``."""
    found = []
    for review in reviews:
        user = review.get("user") or {}
        if (
            isinstance(user, Mapping)
            and user.get("login") == REVIEW_BOT_LOGIN
            and review.get("state") in SUBMITTED_STATES
            and str(review.get("body") or "").strip()
            and review.get("commit_id") == head_sha
        ):
            found.append(f"review {review.get('id')} ({review.get('state')})")
    return found


def check_target(repo: str, expect_repo: str, current_repo: str = "") -> None:
    """Refuse to act on anything but the configured scratch repo (never the caller's own)."""
    if not expect_repo or repo.lower() != expect_repo.lower():
        raise SmokeError(f"refusing to act on {repo!r}: only {expect_repo!r} is allowed")
    if current_repo and repo.lower() == current_repo.lower():
        raise SmokeError(f"refusing to act on {repo!r}: it is the repository running this workflow")


def run_outcome(
    runs: Sequence[Mapping[str, Any]], head_sha: str
) -> tuple[str, Mapping[str, Any] | None]:
    """Classify the newest review workflow run for ``head_sha``.

    Returns ``(state, run)`` where state is ``missing`` (no run yet), ``running``,
    ``concluded`` or ``bad`` (completed without running the review to the end).
    """
    mine = [
        r
        for r in runs
        if r.get("head_sha") == head_sha
        and r.get("path") == REVIEW_WORKFLOW_PATH
        and r.get("event") in PR_EVENTS
    ]
    if not mine:
        return "missing", None
    newest = max(mine, key=lambda r: str(r.get("created_at", "")))
    if newest.get("status") != "completed":
        return "running", newest
    return ("concluded" if newest.get("conclusion") in CONCLUDED else "bad"), newest


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    done: bool
    message: str
    run_url: str = ""


def evaluate(
    runs: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
    issue_comments: Sequence[Mapping[str, Any]],
    review_comments: Sequence[Mapping[str, Any]],
    head_sha: str,
) -> Verdict:
    """Decide the poll outcome. ``done=False`` means keep polling."""
    state, run = run_outcome(runs, head_sha)
    url = str((run or {}).get("html_url") or "")
    if state in {"missing", "running"}:
        return Verdict(False, False, f"review run {state}", url)
    if state == "bad":
        conclusion = (run or {}).get("conclusion")
        return Verdict(False, True, f"review run ended '{conclusion}' without completing", url)
    if (run or {}).get("conclusion") == "failure":
        # A crashed run can leave an error comment; only a submitted review on the head
        # commit proves the review itself was produced.
        submitted = submitted_review_evidence(reviews, head_sha)
        if not submitted:
            return Verdict(
                False,
                True,
                "review run failed and no submitted pull request review exists on the head commit",
                url,
            )
        return Verdict(
            True, True, f"review posted: {', '.join(submitted)} (run failed: final gate)", url
        )
    evidence = review_posted(reviews, issue_comments, review_comments)
    if not evidence:
        return Verdict(False, True, "review run concluded but no review or comment was posted", url)
    return Verdict(True, True, f"review posted: {', '.join(evidence)}", url)


def cleanup_plan() -> list[str]:
    """Cleanup order: stop activity before removing refs, restore main last-but-secrets."""
    return ["close_pull_requests", "delete_branches", "reset_main", "delete_secrets"]


def wait_for_review(
    fetch: Callable[[], Verdict],
    *,
    timeout: float,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Verdict:
    """Poll ``fetch`` until it is done or ``timeout`` elapses (bounded)."""
    deadline = clock() + timeout
    last = Verdict(False, False, "no poll completed")
    while True:
        last = fetch()
        if last.done:
            return last
        if clock() + interval > deadline:
            return Verdict(
                False, True, f"timed out after {timeout:.0f}s: {last.message}", last.run_url
            )
        sleep(interval)


# ----------------------------------------------------------------------- side effects


@dataclass(slots=True)
class Context:
    repo: str
    token: str
    api_key: str
    runner: Runner = subprocess.run
    log: Callable[[str], None] = field(default=lambda m: print(m, flush=True))

    def env(self) -> dict[str, str]:
        env = {
            k: v for k, v in os.environ.items() if k not in {"GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"}
        }
        env["GH_TOKEN"] = self.token
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def sh(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> str:
        """Run ``argv`` (never through a shell), echo redacted output, return stdout."""
        proc = self.runner(
            list(argv),
            cwd=cwd,
            input=stdin,
            text=True,
            capture_output=True,
            env=dict(env or self.env()),
        )
        secrets = (self.token, self.api_key)
        for stream in (proc.stdout, proc.stderr):
            if stream:
                self.log(redact(stream.rstrip(), secrets))
        if check and proc.returncode != 0:
            raise SmokeError(f"`{' '.join(argv[:3])} ...` exited {proc.returncode}")
        return proc.stdout or ""

    def api(self, path: str, *extra: str, method: str = "GET") -> Any:
        out = self.sh(["gh", "api", "-X", method, path, *extra], check=True)
        return json.loads(out) if out.strip() else None


def discover_root_sha(ctx: Context) -> str:
    """Return the scratch repo's single root commit on ``main`` (the known-good reset target)."""
    out = ctx.sh(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{ctx.repo}/commits?sha=main&per_page=100",
            "--jq",
            ".[] | select(.parents | length == 0) | .sha",
        ]
    )
    roots = out.split()
    if len(roots) != 1:
        raise SmokeError(f"scratch repo main must have exactly one root commit, found {len(roots)}")
    return roots[0]


def cleanup(ctx: Context, base_sha: str) -> list[str]:
    """Reset the scratch repo; every step is attempted, failures are collected."""
    errors: list[str] = []

    def close_pull_requests() -> None:
        for pr in ctx.api(f"repos/{ctx.repo}/pulls?state=open&per_page=100") or []:
            if str(pr["head"]["ref"]).startswith(BRANCH_PREFIX):
                ctx.api(
                    f"repos/{ctx.repo}/pulls/{pr['number']}", "-f", "state=closed", method="PATCH"
                )

    def delete_branches() -> None:
        for ref in ctx.api(f"repos/{ctx.repo}/git/matching-refs/heads/{BRANCH_PREFIX}") or []:
            ctx.api(f"repos/{ctx.repo}/git/{ref['ref']}", method="DELETE")

    def reset_main() -> None:
        ctx.api(
            f"repos/{ctx.repo}/git/refs/heads/main",
            "-f",
            f"sha={base_sha}",
            "-F",
            "force=true",
            method="PATCH",
        )

    def delete_secrets() -> None:
        listing = ctx.api(f"repos/{ctx.repo}/actions/secrets?per_page=100") or {}
        for secret in listing.get("secrets", []):
            if str(secret["name"]).startswith(SECRET_PREFIX):
                ctx.sh(["gh", "secret", "delete", secret["name"], "--repo", ctx.repo])

    steps = {
        f.__name__: f for f in (close_pull_requests, delete_branches, reset_main, delete_secrets)
    }
    for name in cleanup_plan():
        try:
            steps[name]()
            ctx.log(f"cleanup: {name} ok")
        except (SmokeError, OSError, ValueError, KeyError) as exc:
            errors.append(f"{name}: {exc}")
            ctx.log(f"cleanup: {name} FAILED: {exc}")
    return errors


def _paginated(ctx: Context, path: str) -> list[dict[str, Any]]:
    sep = "&" if "?" in path else "?"
    data = ctx.api(f"{path}{sep}per_page=100")
    return list(data or [])


def run_scenario(ctx: Context, args: argparse.Namespace) -> Verdict:
    """Follow the Quickstart as a new user would, then wait for and assert the review."""
    spec = readme_install_spec(args.readme.read_text(encoding="utf-8"), args.version)
    work = args.workdir or Path(tempfile.mkdtemp(prefix="quickstart-smoke-"))
    clone, tools = work / "repo", work / "tools"
    tool_env = {
        **ctx.env(),
        "UV_TOOL_DIR": str(tools / "dir"),
        "UV_TOOL_BIN_DIR": str(tools / "bin"),
    }
    tool_env["PATH"] = f"{tools / 'bin'}{os.pathsep}{tool_env['PATH']}"

    ctx.log(f"== install ({args.install})")
    target = spec if args.install == "release" else str(args.source_dir.resolve())
    ctx.sh(["uv", "tool", "install", "--force", target], env=tool_env)
    ctx.sh(["mergecraft", "--version"], env=tool_env)

    ctx.log(f"== clone {ctx.repo}")
    ctx.sh(["gh", "repo", "clone", ctx.repo, str(clone)])
    git = ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
    ctx.sh([*git, "config", "user.name", "mergecraft-smoke"], cwd=clone)
    ctx.sh([*git, "config", "user.email", "mergecraft-smoke@users.noreply.github.com"], cwd=clone)
    roots = ctx.sh([*git, "rev-list", "--max-parents=0", "HEAD"], cwd=clone).split()
    if len(roots) != 1:
        raise SmokeError(f"scratch repo main must have exactly one root commit, found {len(roots)}")
    base_sha = roots[0]
    head_main = ctx.sh([*git, "rev-parse", "HEAD"], cwd=clone).strip()
    if head_main != base_sha:
        ctx.log("scratch main is not at its root commit (stale prior run); resetting it first")
        stale = cleanup(ctx, base_sha)
        if stale:
            raise SmokeError(f"could not restore the scratch repo to a known state: {stale}")
        ctx.sh([*git, "fetch", "origin"], cwd=clone)
        ctx.sh([*git, "reset", "--hard", base_sha], cwd=clone)

    ctx.log("== mergecraft init")
    ctx.sh(["mergecraft", "init"], cwd=clone, env=tool_env)

    ctx.log(f"== mergecraft provider auth {args.provider} --scope github")
    # No flag stores the key as an Actions secret non-interactively (--api-key is local-only),
    # so the key goes to the prompt's stdin fallback; never on argv.
    ctx.sh(
        ["mergecraft", "provider", "auth", args.provider, "--scope", "github"],
        cwd=clone,
        stdin=ctx.api_key + "\n",
        env=tool_env,
    )
    ctx.sh(
        ["mergecraft", "agent", "assign-model", "reviewer", "p0", args.model],
        cwd=clone,
        env=tool_env,
    )
    ctx.sh(["mergecraft", "doctor"], cwd=clone, env=tool_env, check=False)

    ctx.log("== push scaffold to main")
    ctx.sh([*git, "add", "-A"], cwd=clone)
    ctx.sh([*git, "commit", "-m", "chore: mergecraft quickstart scaffold"], cwd=clone)
    ctx.sh([*git, "push", "origin", "HEAD:main"], cwd=clone)

    branch = branch_name(args.run_id, args.install)
    ctx.log(f"== open PR from {branch}")
    ctx.sh([*git, "checkout", "-b", branch], cwd=clone)
    (clone / "smoke_math.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )
    ctx.sh([*git, "add", "smoke_math.py"], cwd=clone)
    ctx.sh([*git, "commit", "-m", "feat: add a trivial helper"], cwd=clone)
    ctx.sh([*git, "push", "origin", branch], cwd=clone)
    head_sha = ctx.sh([*git, "rev-parse", "HEAD"], cwd=clone).strip()
    pr = ctx.api(
        f"repos/{ctx.repo}/pulls",
        "-f",
        f"head={branch}",
        "-f",
        "base=main",
        "-f",
        "title=smoke: trivial change",
        "-f",
        "body=Automated Quickstart smoke.",
        method="POST",
    )
    number = pr["number"]
    ctx.log(f"PR: {pr['html_url']}")

    def fetch() -> Verdict:
        runs = (
            ctx.api(f"repos/{ctx.repo}/actions/runs?head_sha={head_sha}&per_page=100") or {}
        ).get("workflow_runs", [])
        return evaluate(
            runs,
            _paginated(ctx, f"repos/{ctx.repo}/pulls/{number}/reviews"),
            _paginated(ctx, f"repos/{ctx.repo}/issues/{number}/comments"),
            _paginated(ctx, f"repos/{ctx.repo}/pulls/{number}/comments"),
            head_sha,
        )

    ctx.log("== waiting for the mergeCraft review")
    return wait_for_review(fetch, timeout=args.timeout, interval=args.poll_interval)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("SMOKE_REPO_TOKEN", "")
    api_key = os.environ.get("SMOKE_PROVIDER_API_KEY", "")
    if not token or (args.command == "run" and not api_key):
        print("::error title=quickstart smoke::SMOKE_REPO_TOKEN / SMOKE_PROVIDER_API_KEY not set")
        return 2
    try:
        check_target(args.repo, args.expect_repo, os.environ.get("GITHUB_REPOSITORY", ""))
    except SmokeError as exc:
        print(f"::error title=quickstart smoke::{exc}")
        return 2
    ctx = Context(repo=args.repo, token=token, api_key=api_key, runner=subprocess.run)

    if args.command == "cleanup":
        try:
            errors = cleanup(ctx, discover_root_sha(ctx))
        except SmokeError as exc:
            errors = [f"discover_root_sha: {exc}"]
        for error in errors:
            print(f"::error title=quickstart smoke cleanup::{redact(error, (token, api_key))}")
        return 1 if errors else 0

    try:
        verdict = run_scenario(ctx, args)
    except SmokeError as exc:
        print(
            f"::error title=quickstart smoke ({args.install})::{redact(str(exc), (token, api_key))}"
        )
        return 1
    where = f" Review run: {verdict.run_url}" if verdict.run_url else ""
    if verdict.ok:
        print(f"quickstart smoke ({args.install}) passed: {verdict.message}.{where}")
        return 0
    print(
        f"::error title=quickstart smoke ({args.install})::{verdict.message}.{where} Scratch repo: https://github.com/{args.repo}/actions"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
