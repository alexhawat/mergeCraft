#!/usr/bin/env python3
"""Mint / revoke a GitHub App installation token (companion action)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def _emit_output(name: str, value: str) -> None:
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")
    print(f"::add-mask::{value}", flush=True)
    print(f"::set-output name={name}::{value}", flush=True)  # legacy runners


async def _mint() -> None:
    # Prefer installed package; fall back to src layout for composite checkout.
    try:
        from mergecraft.utils.token import acquire_installation_token
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from mergecraft.utils.token import acquire_installation_token

    repos_input = os.environ.get("INPUT_REPOS", "").strip()
    additional = [r.strip() for r in repos_input.split(",") if r.strip()] if repos_input else []
    token = await acquire_installation_token(repos=additional or None)
    _emit_output("token", token)
    state_file = os.environ.get("GITHUB_STATE")
    if state_file:
        with open(state_file, "a", encoding="utf-8") as fh:
            fh.write(f"token={token}\n")
    scope = f"current repo + {', '.join(additional)}" if additional else "current repo only"
    print(f"» installation token acquired ({scope})", flush=True)


async def _revoke() -> None:
    try:
        from mergecraft.utils.token import revoke_installation_token
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from mergecraft.utils.token import revoke_installation_token

    token = os.environ.get("STATE_token", "").strip()
    if not token:
        print("no token found in state, skipping revocation", flush=True)
        return
    await revoke_installation_token(token)
    print("» installation token revoked", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mint or revoke a GitHub App installation token")
    parser.add_argument("--post", action="store_true", help="Revoke previously minted token")
    args = parser.parse_args(argv)
    if args.post or os.environ.get("MERGECRAFT_TOKEN_POST") == "1":
        asyncio.run(_revoke())
    else:
        asyncio.run(_mint())


if __name__ == "__main__":
    main()
