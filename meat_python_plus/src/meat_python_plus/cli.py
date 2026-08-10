"""CLI matching Go meat UX: HEAD / revision / range / -staged / -w / stdin / flags."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Callable, TextIO

from meat_python_plus.abridge import Request, Result, abridge
from meat_python_plus.cache import cache_key, cache_load, cache_store, default_cache_dir
from meat_python_plus.diffutil import elision_line
from meat_python_plus.providers.resolve import new_model_from_env, resolve_model_name
from meat_python_plus.rubric import rubric_hash

USAGE = """meat_python_plus — abridge a diff into a "reading diff"

Usage:
  meat-py                         Summarize the most recent commit (HEAD).
  meat-py <rev>                   Summarize a specific commit or revision.
  meat-py <rev1>..<rev2>          Diff across a commit range.
  meat-py -staged                 Abridge staged (index) changes.
  meat-py -w                      Abridge unstaged working-tree changes.
  git show | meat-py              Abridge a diff piped on stdin.

Results are cached under ~/.meat_python_plus keyed by SHA of
(protocol version + system prompt + model + diff).

Flags:
  -model string   Model id (default $MEAT_MODEL or gpt-4.1-mini).
  -no-cache       Ignore cached result and recompute (still updates cache).
  -staged         Read staged changes (git diff --staged).
  -w              Read unstaged working-tree changes (git diff).
  -json           Emit JSON on stdout.
  -h, --help      Show this help.

Environment:
  OPENAI_API_KEY / OPENAI_BASE_URL
  ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL
  NOUS_API_KEY          Nous Portal (https://inference-api.nousresearch.com/v1)
  TOKENHUB_API_KEY      Tencent TokenHub (https://tokenhub-intl.tencentcloudmaas.com/v1)
  MEAT_BASE_URL + MEAT_API_KEY   Custom OpenAI-compatible endpoint
  MEAT_MODEL / MEAT_CACHE
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="meat-py",
        description='Abridge a unified diff into a "reading diff".',
        add_help=False,
    )
    parser.add_argument("-model", dest="model", default="", help="model id")
    parser.add_argument("-no-cache", dest="no_cache", action="store_true")
    parser.add_argument("-staged", dest="staged", action="store_true")
    parser.add_argument("-w", dest="worktree", action="store_true")
    parser.add_argument("-json", dest="json_out", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("revision", nargs="?", default=None)

    # Accept Go-style flags that argparse already covers; also tolerate --model.
    normalized: list[str] = []
    for a in argv:
        if a == "--model":
            normalized.append("-model")
        elif a == "--no-cache":
            normalized.append("-no-cache")
        elif a == "--staged":
            normalized.append("-staged")
        elif a == "--json":
            normalized.append("-json")
        else:
            normalized.append(a)

    try:
        args, unknown = parser.parse_known_args(normalized)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    if args.help:
        sys.stderr.write(USAGE)
        return 0
    if unknown:
        fatal(f"unknown arguments: {' '.join(unknown)}")
        return 2

    try:
        diff, source = read_diff(args.revision, args.staged, args.worktree)
    except ValueError as e:
        fatal(str(e))
        return 1
    if not diff.strip():
        fatal(f"no diff to read ({source})")
        return 1

    json_out = args.json_out
    interactive = (
        not json_out and sys.stdout.isatty() and sys.stderr.isatty()
    )

    def progress(msg: str) -> None:
        if interactive:
            sys.stderr.write(f"\r\x1b[Kmeat: {msg}")
            sys.stderr.flush()

    model_name = resolve_model_name(args.model)
    rubric = rubric_hash()
    cache_dir = default_cache_dir()

    def compute() -> Result:
        m = new_model_from_env(args.model)
        return abridge(
            m,
            Request(
                unified_diff=diff,
                repo_root=git_root(),
                progress=progress if interactive else None,
            ),
        )

    def render(res: Result) -> None:
        if interactive:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()
        elision = elision_line(diff, res.smart_diff)
        if json_out:
            payload = res.to_dict()
            payload["elision"] = elision
            json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
            return
        if res.summary:
            sys.stdout.write(res.summary + "\n")
        if elision:
            sys.stdout.write(f"({elision})\n")
        if res.smart_diff:
            if res.summary or elision:
                sys.stdout.write("\n")
            sys.stdout.write(res.smart_diff)
            if not res.smart_diff.endswith("\n"):
                sys.stdout.write("\n")

    try:
        run(
            diff=diff,
            model=model_name,
            rubric=rubric,
            cache_dir=cache_dir,
            no_cache=args.no_cache,
            compute=compute,
            render=render,
            stderr=sys.stderr,
            interactive=interactive,
        )
    except Exception as e:
        if interactive:
            sys.stderr.write("\r\x1b[K")
        fatal(str(e))
        return 1
    return 0


def run(
    *,
    diff: str,
    model: str,
    rubric: str,
    cache_dir: str,
    no_cache: bool,
    compute: Callable[[], Result],
    render: Callable[[Result], None],
    stderr: TextIO,
    interactive: bool = False,
) -> None:
    key = cache_key(diff, model, rubric)
    if not no_cache:
        hit = cache_load(cache_dir, key)
        if hit is not None:
            render(Result.from_dict(hit))
            stderr.write(f"\nmeat: cached (sha {key[:12]})\n")
            return

    start = time.time()
    res = compute()
    elapsed = time.time() - start
    cache_store(cache_dir, key, res.to_dict())
    render(res)
    stderr.write(
        f"\nmeat: tokens in={res.input_tokens} out={res.output_tokens} "
        f"in {elapsed:.1f}s\n"
    )


def read_diff(revision: str | None, staged: bool, worktree: bool) -> tuple[str, str]:
    if staged and worktree:
        raise ValueError("-staged and -w are mutually exclusive")
    if (staged or worktree) and revision:
        raise ValueError("-staged/-w cannot be combined with a revision argument")
    if staged:
        return git("diff", "--staged"), "staged; nothing staged?"
    if worktree:
        return git("diff"), "worktree; no unstaged changes?"
    if revision:
        if ".." in revision:
            return git("diff", revision), revision
        return git_show(revision), revision
    if not sys.stdin.isatty():
        return sys.stdin.read(), "stdin"
    return git_show("HEAD"), "HEAD"


def git_show(rev: str) -> str:
    return git("show", "--format=fuller", "-m", "--first-parent", rev)


def git(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise ValueError(str(e)) from e
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        raise ValueError(f"git {' '.join(args)}: {err}")
    return proc.stdout


def git_root() -> str:
    try:
        return git("rev-parse", "--show-toplevel").strip()
    except ValueError:
        return ""


def fatal(msg: str) -> None:
    if not msg.startswith("meat:"):
        msg = "meat: " + msg
    print(msg, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
