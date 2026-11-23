#!/usr/bin/env python3
"""Build golden-batch-002.source.json for hitl from the packet prose plus upstream GitHub data.

For every case it fetches, at the pinned commits: the PR base/head/merge SHAs (checked against
the packet), the fix PR body (checked for the quoted causal statement), the claimed file at the
introducing merge (excerpt around the claimed lines), and the introducing and fix PR diffs for
that file. Nothing is decided here: every item goes in pending.

Usage (needs an authenticated `gh`):
    python3 evals/adjudication/golden-batch-002-hitl/build_hitl_source.py
    curl -X POST "$HITL_URL/api/v1/sources/upload" -H 'Content-Type: application/json' \
        --data-binary @evals/adjudication/golden-batch-002-hitl/golden-batch-002.source.json
"""

import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cases import CASES

CONTEXT = 4


def say(line):
    sys.stdout.write(line + "\n")


def pr_link(repo, number):
    return f"https://github.com/{repo}/pull/{number}"


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"gh api {path}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def pr_files(repo, number):
    files, page = [], 1
    while True:
        batch = gh(f"repos/{repo}/pulls/{number}/files?per_page=100&page={page}")
        files += batch
        if len(batch) < 100:
            return files
        page += 1


def as_diff(f):
    old = f.get("previous_filename", f["filename"])
    return f"--- a/{old}\n+++ b/{f['filename']}\n{f.get('patch') or '(no textual patch: binary or too large)'}\n"


def is_test(name):
    return bool(
        re.search(
            r"(^|/)(tests?|__tests__|playground|dts-test)/|_test\.go$|Tests?\.java$|\.spec\.|\.test-d\.",
            name,
        )
    )


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def build_case(c):
    repo, problems = c["repo"], []
    prs = {}
    for key, num in (("intro", c["intro_pr"]), ("fix", c["fix_pr"])):
        pr = gh(f"repos/{repo}/pulls/{num}")
        prs[key] = pr
        got = (pr["base"]["sha"], pr["head"]["sha"], pr.get("merge_commit_sha"))
        for label, want, have in zip(("base", "head", "merge"), c["pins"][key], got, strict=True):
            if want != have:
                problems.append(
                    f"{key} PR #{num} {label}: packet {want[:12]}, GitHub {str(have)[:12]}"
                )
        if not pr.get("merged_at"):
            problems.append(f"{key} PR #{num} is not merged")
    quote_ok = norm(c["causal_quote"]).lower() in norm(prs["fix"].get("body") or "").lower()
    if not quote_ok:
        problems.append("causal quote not found verbatim in fix PR body")

    blob = gh(f"repos/{repo}/contents/{c['path']}?ref={c['intro_merge']}")
    lines = base64.b64decode(blob["content"]).decode("utf-8").splitlines()
    lo = max(1, c["start_line"] - CONTEXT)
    hi = min(len(lines), c["end_line"] + CONTEXT)
    excerpt = "\n".join(lines[lo - 1 : hi])

    intro_files = pr_files(repo, c["intro_pr"])
    fix_files = pr_files(repo, c["fix_pr"])
    intro_patch = "".join(as_diff(f) for f in intro_files if f["filename"] == c["path"])
    if not intro_patch:
        problems.append(f"introducing PR does not touch {c['path']}")
    fix_src = [f for f in fix_files if f["filename"] == c["path"]] or [
        f for f in fix_files if not is_test(f["filename"])
    ]
    fix_patch = "".join(as_diff(f) for f in fix_src)
    fix_tests = [f["filename"] for f in fix_files if is_test(f["filename"])]

    pin_rows = "\n".join(
        f"| {label} | `{c['pins']['intro'][i]}` | `{c['pins']['fix'][i]}` |"
        for i, label in enumerate(("Base", "Head", "Merge"))
    )
    history = (
        f"[Introducing PR #{c['intro_pr']}]({pr_link(repo, c['intro_pr'])}) merged {prs['intro']['merged_at']} · "
        f"[fix PR #{c['fix_pr']}]({pr_link(repo, c['fix_pr'])}) merged {prs['fix']['merged_at']}\n\n"
        f"| Pin | Introducing PR | Fix PR |\n|---|---|---|\n{pin_rows}\n\n"
        f"Fix PR states: “{c['causal_quote']}”"
    )
    item = {
        "case_id": c["case_id"],
        "review_id": c["review_id"],
        "title": c["title"],
        "language": c["language"],
        "framework": c["framework"],
        "category": c["category"],
        "repo": repo,
        "license": c["license"],
        "license_url": f"https://github.com/{repo}/blob/{c['intro_merge']}/{c['license_file']}",
        "path": c["path"],
        "start_line": c["start_line"],
        "end_line": c["end_line"],
        "evidence_status": "recovered",
        "source_url": f"https://github.com/{repo}/blob/{c['intro_merge']}/{c['path']}#L{c['start_line']}-L{c['end_line']}",
        "introducing_pr_url": pr_link(repo, c["intro_pr"]),
        "fix_pr_url": pr_link(repo, c["fix_pr"]),
        "trigger": c["trigger"],
        "finding": c["finding"],
        "history_md": history,
        "correction": c["correction"],
        "tests": c["tests"],
        "fix_test_files": ", ".join(fix_tests) or None,
        "limits": c["limits"],
        "excerpt": excerpt,
        "excerpt_start": lo,
        "introducing_patch": intro_patch or None,
        "fix_patch": fix_patch or None,
        "evidence_sha256": hashlib.sha256(
            (excerpt + "\0" + intro_patch + "\0" + fix_patch).encode()
        ).hexdigest(),
        "packet_fixture_sha256": c["packet_hash"],
        "verification": "pins and causal quote match GitHub"
        if not problems
        else "; ".join(problems),
        "verified": not problems,
    }
    return item, problems


S = {"type": "string"}
NS = {"type": ["string", "null"]}
WORKFLOW = {
    "schema_version": "1",
    "id": "mergecraft-golden-b002",
    "version": 1,
    "title": "mergeCraft golden batch 002 adjudication",
    "description": "A human confirms, corrects, or abstains on each agent-proposed regression finding, judged against the pinned upstream code and PR diffs.",
    "item": {
        "id_field": "case_id",
        "schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "case_id",
                "review_id",
                "title",
                "category",
                "path",
                "start_line",
                "end_line",
                "finding",
                "excerpt",
                "evidence_status",
            ],
            "properties": {
                **{
                    k: S
                    for k in (
                        "case_id",
                        "review_id",
                        "title",
                        "language",
                        "framework",
                        "category",
                        "repo",
                        "license",
                        "license_url",
                        "path",
                        "source_url",
                        "introducing_pr_url",
                        "fix_pr_url",
                        "trigger",
                        "finding",
                        "history_md",
                        "correction",
                        "tests",
                        "limits",
                        "excerpt",
                        "verification",
                    )
                },
                **{k: NS for k in ("fix_test_files", "introducing_patch", "fix_patch")},
                "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "packet_fixture_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
                "excerpt_start": {"type": "integer", "minimum": 1},
                "evidence_status": {"enum": ["recovered", "missing"]},
                "verified": {"type": "boolean"},
            },
        },
    },
    "display": {
        "eyebrow": "{review_id} · {case_id}",
        "blocks": [
            {"type": "heading", "field": "title"},
            {
                "type": "callout",
                "tone": "neutral",
                "text": "Agent-proposed finding, pending your adjudication. Judge it against the pinned upstream code and diffs below, not the agent's wording.",
            },
            {
                "type": "callout",
                "tone": "warning",
                "show_if": {"field": "verified", "equals": False},
                "field": "verification",
            },
            {
                "type": "facts",
                "items": [
                    {
                        "label": "Claimed location",
                        "template": "{path}:{start_line}-{end_line}",
                        "style": "mono",
                    },
                    {"label": "Proposed category", "field": "category", "style": "badge"},
                    {"label": "Language / framework", "template": "{language} / {framework}"},
                    {"label": "Upstream", "template": "{repo} ({license})"},
                    {
                        "label": "Evidence",
                        "field": "evidence_status",
                        "style": "badge",
                        "tones": {"recovered": "ok", "missing": "warning"},
                    },
                    {"label": "Checked against GitHub", "field": "verification"},
                ],
            },
            {"type": "text", "label": "Trigger", "field": "trigger"},
            {"type": "text", "label": "Proposed finding", "field": "finding"},
            {"type": "markdown", "label": "Upstream history", "field": "history_md"},
            {
                "type": "link",
                "label": "Pinned source at the introducing merge",
                "field": "source_url",
            },
            {
                "type": "code",
                "label": "Code at the claimed location (introducing merge)",
                "field": "excerpt",
                "language": "{language}",
                "start_line_field": "excerpt_start",
            },
            {
                "type": "diff",
                "label": "Introducing PR diff for this file",
                "field": "introducing_patch",
                "highlight": {
                    "path_field": "path",
                    "start_field": "start_line",
                    "end_field": "end_line",
                },
                "show_if": {"field": "introducing_patch", "present": True},
            },
            {
                "type": "diff",
                "label": "Fix PR diff",
                "field": "fix_patch",
                "show_if": {"field": "fix_patch", "present": True},
            },
            {"type": "text", "label": "Correction in the merged fix", "field": "correction"},
            {"type": "text", "label": "Test evidence", "field": "tests"},
            {
                "type": "text",
                "label": "Test files in the fix PR",
                "field": "fix_test_files",
                "show_if": {"field": "fix_test_files", "present": True},
            },
            {"type": "text", "label": "Limits", "field": "limits"},
            {"type": "link", "label": "License", "field": "license_url"},
        ],
    },
    "question": {
        "text": "Does the proposed finding hold at the claimed location, within its stated scope?",
        "help": "Confirm accepts the finding and its scope. Correct if it is real but the claim, location or category is wrong. Abstain if the evidence does not let you decide.",
    },
    "form": {
        "fields": [
            {
                "name": "decision",
                "label": "Decision",
                "type": "choice",
                "required": True,
                "options": [
                    {
                        "value": "confirm",
                        "label": "Confirm",
                        "help": "The finding holds at the claimed location, within its stated scope.",
                    },
                    {
                        "value": "correct",
                        "label": "Correct",
                        "help": "The finding is real but the claim, location or category is wrong.",
                    },
                    {
                        "value": "abstain",
                        "label": "Abstain",
                        "help": "The evidence does not let you decide.",
                    },
                ],
            },
            {
                "name": "corrected_fields",
                "label": "Corrected fields",
                "type": "group",
                "show_if": {"answer": "decision", "equals": "correct"},
                "required": "at_least_one",
                "fields": [
                    {"name": "finding", "label": "Corrected claim", "type": "textarea"},
                    {
                        "name": "category",
                        "label": "Category",
                        "type": "text",
                        "placeholder_field": "category",
                    },
                    {"name": "path", "label": "Path", "type": "text", "placeholder_field": "path"},
                    {
                        "name": "start_line",
                        "label": "Start line",
                        "type": "integer",
                        "min": 1,
                        "placeholder_field": "start_line",
                    },
                    {
                        "name": "end_line",
                        "label": "End line",
                        "type": "integer",
                        "min": 1,
                        "placeholder_field": "end_line",
                    },
                ],
            },
            {
                "name": "notes",
                "label": "Notes",
                "type": "textarea",
                "help": "Optional. For Abstain, what evidence is missing or what is uncertain.",
            },
        ]
    },
    "output": {
        "format": "json",
        "include": "answered",
        "envelope": {
            "batch_id": {"source_meta": "batch_id"},
            "adjudicator_login": {"source_meta": "adjudicator_login"},
        },
        "records_key": "cases",
        "record": {
            "review_id": {"item": "review_id"},
            "case_id": {"item": "case_id"},
            "evidence_sha256": {"item": "evidence_sha256"},
            "decision": {"answer": "decision"},
            "decided_at": {"response": "submitted_at"},
            "decided_by": {"response": "user"},
            "corrected_fields": {"answer": "corrected_fields", "empty_as": None},
            "notes": {"answer": "notes", "empty_as": None},
        },
    },
}


def main():
    items = []
    for c in CASES:
        item, problems = build_case(c)
        items.append(item)
        say(
            f"{c['review_id']}: {'ok' if not problems else 'CHECK ' + '; '.join(problems)}"
            f" | intro diff {len(item['introducing_patch'] or '')}b, fix diff {len(item['fix_patch'] or '')}b"
        )
    source = {
        "schema_version": "1",
        "source_id": "golden-batch-002",
        "title": "mergeCraft golden batch 002 (pending human review)",
        "workflow": WORKFLOW,
        "meta": {
            "batch_id": "golden-batch-002",
            "adjudicator_login": "alexhawat",
            "prepared": "2026-11-19",
            "tracking_issue": "https://github.com/alexhawat/mergeCraft/issues/780",
            "note": "Agent-proposed candidates staged for review; not published golden corpus rows.",
        },
        "items": items,
    }
    out = Path(__file__).with_name("golden-batch-002.source.json")
    out.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    say(f"wrote {out} ({len(items)} items, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
