#!/usr/bin/env python3
"""Prepare the two reviewed commits C (manifest) then P (consumer pin).

Preparation never commits, pushes Git branches, creates PRs, or claims CI ran. Both phases
require signed image verification; the pin phase requires C already merged.
The CI-only publish-canonical phase writes registry tags after strict verification.
Exports: prepare_manifest, prepare_pin, resolve_images, publish_canonical, main.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from check_action_image_digest import (
    REPO,
    SLIM_IMAGE,
    TagLookupStatus,
    VerificationError,
    _commit,
    _ghcr_digest_for_tag,
    _ghcr_digest_for_tag_once,
    _git,
    _run,
    verify_image,
    verify_manifest,
)

_IMAGE_LINE = re.compile(
    r"(?m)^([ \t]*image:[ \t]*[\"']?)docker://ghcr\.io/alexhawat/mergecraft@sha256:[0-9a-f]{64}([\"']?[ \t]*(?:#.*)?)$"
)

_PIN = re.compile(r"(uses:\s*alexhawat/mergeCraft@)[0-9a-f]{40}")
_ENV_PIN = re.compile(r'(?m)^(\s*MERGECRAFT_ACTION_SHA:\s*["\']?)[0-9a-f]{40}')


def _prepared_state(repo: Path, expected: dict[str, str]) -> bool:
    """Allow only exact unstaged prepared bytes; never absorb staged/untracked edits."""
    if _git(repo, "diff", "--cached", "--name-only").strip():
        raise VerificationError("staged changes must be committed or unstaged before preparation")
    if _git(repo, "ls-files", "--others", "--exclude-standard").strip():
        raise VerificationError("untracked files are not part of a prepared release change")
    if _git(repo, "diff", "--summary").strip():
        raise VerificationError("file modes and paths must not change during preparation")
    changed = set(_git(repo, "diff", "--name-only").splitlines())
    if not changed <= expected.keys():
        raise VerificationError("unexpected dirty files outside the prepared release change")
    for name in changed:
        path = repo / name
        if path.is_symlink() or not path.is_file() or path.read_text() != expected[name]:
            raise VerificationError("dirty content is not the exact prepared release change")
    return bool(changed)


def prepare_manifest(repo: Path, source: str, digest: str) -> dict[str, str | None]:
    """Prepare only the image patch, or recognize its exact uncommitted state."""
    source = _commit(source)
    head = _commit(_git(repo, "rev-parse", "HEAD").strip())
    if head != source:
        _prepared_state(repo, {})
        result = verify_manifest(repo, head)
        if result.source_revision != source or result.image_digest != digest:
            raise VerificationError("HEAD is not the built source or its verified manifest")
        return {
            "state": "manifest-already-present",
            "manifest_commit": head,
            "source_revision": source,
            "image_digest": digest,
        }
    baseline = _git(repo, "show", f"{source}:action.yml")
    content, count = _IMAGE_LINE.subn(
        lambda match: f"{match[1]}docker://ghcr.io/alexhawat/mergecraft@{digest}{match[2]}",
        baseline,
    )
    if count != 1:
        raise VerificationError("expected exactly one digest image line")
    _prepared_state(repo, {"action.yml": content})
    verify_image(repo, digest, source)
    if content == baseline:
        return {
            "state": "manifest-already-present",
            "manifest_commit": head,
            "source_revision": source,
            "image_digest": digest,
        }
    (repo / "action.yml").write_text(content)
    return {
        "state": "manifest-change-prepared",
        "manifest_commit": None,
        "source_revision": source,
        "image_digest": digest,
    }


def prepare_pin(repo: Path, manifest: str, base_branch: str = "pre-0.0.1") -> dict[str, str]:
    """Prepare literal and environment references to merged C, accepting exact reruns."""
    head = _commit(_git(repo, "rev-parse", "HEAD").strip())
    manifest = _commit(manifest)
    if base_branch not in ("main", "pre-0.0.1"):
        raise VerificationError("consumer pins target main or pre-0.0.1 only")
    _git(repo, "merge-base", "--is-ancestor", manifest, f"origin/{base_branch}")
    _git(repo, "merge-base", "--is-ancestor", manifest, head)
    expected: dict[str, str] = {}
    changed = False
    consumer_pins = 0
    candidates = [
        f".github/workflows/{name}" for name in ("mergecraft.yml", "mergecraft-approve.yml")
    ]
    tracked = _git(repo, "ls-tree", "--name-only", head, "--", *candidates).splitlines()
    for name in tracked:
        content = _git(repo, "show", f"{head}:{name}")
        consumer_pins += len(_PIN.findall(content)) + len(_ENV_PIN.findall(content))
        replaced = _ENV_PIN.sub(
            lambda match: match[1] + manifest, _PIN.sub(lambda match: match[1] + manifest, content)
        )
        expected[name] = replaced
        changed = changed or replaced != content
    if not consumer_pins:
        raise VerificationError("no self-review consumer Action references found")
    _prepared_state(repo, expected)
    result = verify_manifest(repo, manifest)
    if changed:
        for name, content in expected.items():
            (repo / name).write_text(content)
    return {
        "state": "pin-change-prepared" if changed else "pin-already-present",
        "manifest_commit": manifest,
        "source_revision": result.source_revision,
        "image_digest": result.image_digest,
    }


def _shared_image_repository() -> None:
    """Both kinds share one GHCR repository; reject configuration drift explicitly."""
    for variable in ("IMAGE_SLIM", "IMAGE_ANALYZERS"):
        if os.environ.get(variable, SLIM_IMAGE) != SLIM_IMAGE:
            raise VerificationError(f"{variable} must equal the shared repository {SLIM_IMAGE}")


def resolve_images(repo: Path, source: str) -> dict[str, str]:
    """Reuse only verified SHA tags; registry errors/unsigned collisions fail closed."""
    _shared_image_repository()
    source = _commit(source)
    outputs: dict[str, str] = {}
    for kind, tag in (("slim", source), ("analyzers", f"analyzers-{source}")):
        lookup = _ghcr_digest_for_tag_once(tag)
        if lookup.status is TagLookupStatus.ERROR:
            raise VerificationError("registry unavailable: cannot determine immutable tag state")
        if lookup.status is TagLookupStatus.MISSING:
            outputs[f"{kind}_digest"] = ""
            continue
        if lookup.digest is None:
            raise VerificationError("registry returned an empty image digest")
        verify_image(repo, lookup.digest, source, require_tracing=kind == "slim")
        outputs[f"{kind}_digest"] = lookup.digest
    return outputs


def publish_canonical(repo: Path, source: str, digests: dict[str, str]) -> dict[str, str]:
    """Publish verified canonical tags while the workflow holds the source-S lock."""
    _shared_image_repository()
    source = _commit(source)
    if set(digests) != {"slim", "analyzers"}:
        raise VerificationError("both image digests are required before canonical publication")
    pending: list[tuple[str, str]] = []
    # Check both kinds before writing either. A resumed partial publication is
    # valid only when the existing tag already equals the requested digest.
    for kind, digest in digests.items():
        verify_image(repo, digest, source, require_tracing=kind == "slim")
        tag = source if kind == "slim" else f"analyzers-{source}"
        current = _ghcr_digest_for_tag_once(tag)
        if current.status is TagLookupStatus.ERROR:
            raise VerificationError("registry unavailable during canonical publication")
        if current.status is TagLookupStatus.FOUND:
            if current.digest != digest:
                raise VerificationError("canonical source tag already names a different digest")
        else:
            pending.append((tag, digest))
    for tag, digest in pending:
        _run(
            repo,
            [
                "docker",
                "buildx",
                "imagetools",
                "create",
                "--prefer-index=false",
                "--tag",
                f"{SLIM_IMAGE}:{tag}",
                f"{SLIM_IMAGE}@{digest}",
            ],
        )
        published = _ghcr_digest_for_tag(tag)
        if published.status is not TagLookupStatus.FOUND or published.digest != digest:
            raise VerificationError("canonical tag readback differs from verified digest")
    return {"state": "canonical-images-published", "source_revision": source, **digests}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("manifest", "pin", "resolve-images", "verify-images", "publish-canonical")
    )
    parser.add_argument("--source", default=os.environ.get("SOURCE_REVISION"))
    parser.add_argument("--digest", default=os.environ.get("IMAGE_DIGEST"))
    parser.add_argument("--manifest", default=os.environ.get("MANIFEST_COMMIT"))
    parser.add_argument("--base-branch", default=os.environ.get("RELEASE_BASE_BRANCH", "pre-0.0.1"))
    args = parser.parse_args(argv)
    try:
        if args.phase == "manifest":
            result = prepare_manifest(REPO, args.source or "", args.digest or "")
        elif args.phase == "pin":
            result = prepare_pin(REPO, args.manifest or "", args.base_branch)
        elif args.phase == "resolve-images":
            result = resolve_images(REPO, args.source or "")
            if output := os.environ.get("GITHUB_OUTPUT"):
                with Path(output).open("a") as stream:
                    stream.writelines(f"{key}={value}\n" for key, value in result.items())
        elif args.phase == "publish-canonical":
            result = publish_canonical(
                REPO,
                args.source or "",
                {
                    kind: os.environ.get(f"{kind.upper()}_DIGEST", "")
                    for kind in ("slim", "analyzers")
                },
            )
        else:
            _shared_image_repository()
            source = _commit(args.source or "")
            for kind in ("slim", "analyzers"):
                verify_image(
                    REPO,
                    os.environ.get(f"{kind.upper()}_DIGEST", ""),
                    source,
                    require_tracing=kind == "slim",
                )
            result = {"state": "images-verified", "source_revision": source}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (VerificationError, OSError, ValueError) as exc:
        print(f"action-pin preparation FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
