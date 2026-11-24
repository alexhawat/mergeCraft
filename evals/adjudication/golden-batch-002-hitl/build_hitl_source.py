#!/usr/bin/env python3
"""Build the hitl source for golden batch 002 from the committed review packet and fixtures.

Reads `evals/adjudication/golden-batch-002.json` (the manifest), the prose sections of
`golden-batch-002-review.md`, and each case's fixtures. It fails on any fixture whose SHA-256
differs from the manifest or the case's inventory, on claimed lines that are missing from the
buggy excerpt, and on a causal quote that is missing from the saved fix PR body.

Nothing is decided here. The hitl export uses the manifest's own fields, so it validates as a
`HumanBatchManifest`; `decided_by` is whoever answered in hitl, never filled in from the manifest.

Usage (standard library only; output is deterministic):
    python3 evals/adjudication/golden-batch-002-hitl/build_hitl_source.py
    curl -X POST "$HITL_URL/api/v1/sources/upload" -H 'Content-Type: application/json' \
        --data-binary @evals/adjudication/golden-batch-002-hitl/golden-batch-002.source.json
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADJUDICATION = ROOT / "evals" / "adjudication"
BATCH = "golden-batch-002"
SECTIONS = (
    "When it happens",
    "Proposed finding",
    "Upstream evidence",
    "What the fix changed",
    "Tests and scope",
)
INTRODUCING = ("introducing.patch", "task.patch")
BUGGY = ("buggy-snippet.txt", "introduced-source.txt", "buggy-source.txt")
FIXED = ("fixed-snippet.txt", "fixed-source.txt")
TESTS = ("regression-test-snippet.txt", "regression-tests.txt", "fix-test.txt")
MANIFEST_FIELDS = ("case_id", "evidence_status", "source_url", "fixture_path", "fixture_sha256")


def fail(message):
    sys.exit(f"build_hitl_source: {message}")


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def read_sections():
    """Return {review id: {section heading: text}} from the review packet."""
    text = (ADJUDICATION / f"{BATCH}-review.md").read_text(encoding="utf-8")
    parts = re.split(r"^## (B2-\d\d)$", text, flags=re.M)[1:]
    heading = r"^\*\*(" + "|".join(SECTIONS) + r")\*\*$"
    out = {}
    for review_id, body in zip(parts[::2], parts[1::2], strict=True):
        split = re.split(heading, body, flags=re.M)
        found = dict(zip(split[1::2], split[2::2], strict=True))
        if tuple(found) != SECTIONS:
            fail(f"{review_id}: unexpected packet sections {tuple(found)}")
        out[review_id] = {key: value.strip() for key, value in found.items()}
        out[review_id]["heading"] = split[0].strip()
    return out


def pins_as_list(text):
    """Turn the packet's pin table into a list, because hitl Markdown has no tables."""
    text = re.sub(r"^\| Pin \|.*\n\|---.*\n", "", text, flags=re.M)
    return re.sub(
        r"^\| (\w+) \| (.+?) \| (.+?) \|$", r"- \1: introducing \2, fix \3", text, flags=re.M
    )


def check_fixtures(row, evidence, evidence_path):
    """Check the evidence file and every inventoried artifact against its SHA-256."""
    if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != row["fixture_sha256"]:
        fail(f"{row['case_id']}: evidence.json differs from the manifest hash")
    keys = ("fixture_files_sha256", "artifact_hashes", "artifactsha256")
    inventory = next((evidence[key] for key in keys if key in evidence), None)
    if not inventory:
        fail(f"{row['case_id']}: no artifact inventory")
    for relative, expected in inventory.items():
        path = ROOT / relative if relative.startswith("evals/") else evidence_path.parent / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            fail(f"{row['case_id']}: hash mismatch for {relative}")


def numbered(directory, name, evidence):
    """Return the excerpt with original line numbers, adding them where the file has none."""
    lines = (directory / name).read_text(encoding="utf-8").rstrip("\n").split("\n")
    origin = evidence.get("artifact_origins", {}).get(name, {})
    if "start_line" not in origin:
        return "\n".join(lines)
    return "\n".join(f"{origin['start_line'] + n:4d} {line}" for n, line in enumerate(lines))


def origin_label(name, evidence):
    origin = evidence.get("artifact_origins", {}).get(name, {})
    if origin.get("path"):
        return f"{name}: {origin['path']}"
    for snapshot in evidence.get("source_snapshots", []):
        if Path(snapshot["excerpt_path"]).name == name:
            return f"{name}: {snapshot['path']} ({snapshot['role']})"
    return name


def code_md(directory, names, evidence):
    blocks = [
        f"**{origin_label(name, evidence)}**\n\n`````\n{numbered(directory, name, evidence)}\n`````"
        for name in names
    ]
    return "\n\n".join(blocks) or None


def one(directory, candidates, case_id):
    found = [name for name in candidates if (directory / name).is_file()]
    if len(found) != 1:
        fail(f"{case_id}: expected exactly one of {candidates}, found {found}")
    return found[0]


def line_range(evidence):
    if "buggy_line_range" in evidence:
        return evidence["buggy_line_range"]["start"], evidence["buggy_line_range"]["end"]
    return evidence["start_line"], evidence["end_line"]


def build_item(review_id, row, sections):
    case_id = row["case_id"]
    evidence_path = ROOT / row["fixture_path"]
    directory = evidence_path.parent
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    check_fixtures(row, evidence, evidence_path)
    if evidence["case_id"] != case_id:
        fail(f"{case_id}: evidence declares {evidence['case_id']}")
    if not sections["heading"].startswith(f"**{evidence['title']}**"):
        fail(f"{case_id}: packet section {review_id} is titled {sections['heading']!r}")

    start, end = line_range(evidence)
    buggy = one(directory, BUGGY, case_id)
    shown = {
        int(match.group(1))
        for match in re.finditer(
            r"^\s*(\d+)(?::|\s|$)", numbered(directory, buggy, evidence), flags=re.M
        )
    }
    if not set(range(start, end + 1)) <= shown:
        fail(f"{case_id}: {buggy} does not show claimed lines {start}-{end}")

    causal = evidence["causal_evidence"]
    quote = causal.get("quote") or causal.get("shortquote")
    snapshot = directory / "fix-pr.json"
    fix_body = None
    if snapshot.is_file():
        fix_body = json.loads(snapshot.read_text(encoding="utf-8")).get("body") or ""
        if squash(quote) not in squash(fix_body):
            fail(f"{case_id}: causal quote is not in the saved fix PR body")
        fix_body = "`````\n" + fix_body.replace("\r\n", "\n").strip() + "\n`````"

    used = {buggy, one(directory, FIXED, case_id)}
    tests = [name for name in TESTS if (directory / name).is_file()]
    related = sorted(
        path.name for path in directory.glob("*.txt") if path.name not in used | set(tests)
    )
    return {
        "review_id": review_id,
        **{key: row[key] for key in MANIFEST_FIELDS},
        "title": evidence["title"],
        "language": evidence["language"],
        "framework": evidence["framework"],
        "category": evidence["category"],
        "repo": evidence["repo"],
        "license": evidence["license"]["name"],
        "path": evidence["buggy_file"],
        "start_line": start,
        "end_line": end,
        "trigger": sections["When it happens"],
        "finding": sections["Proposed finding"].split("\n\n")[0],
        "history_md": pins_as_list(sections["Upstream evidence"]),
        "fix_pr_body_md": fix_body,
        "buggy_md": code_md(directory, [buggy], evidence),
        "related_md": code_md(directory, related, evidence),
        "fixed_md": code_md(directory, [one(directory, FIXED, case_id)], evidence),
        "tests_md": code_md(directory, tests, evidence),
        "introducing_patch": (directory / one(directory, INTRODUCING, case_id)).read_text(
            encoding="utf-8"
        ),
        "fix_patch": (directory / "fix.patch").read_text(encoding="utf-8"),
        "correction": sections["What the fix changed"],
        "test_evidence": sections["Tests and scope"].split("\n\n")[0],
        "limits_md": "\n".join(f"- {caveat}" for caveat in evidence["caveats"]),
    }


STRING = {"type": "string", "minLength": 1}
OPTIONAL = {"type": ["string", "null"]}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
LINE = {"type": "integer", "minimum": 1}
OPTIONAL_FIELDS = ("fix_pr_body_md", "related_md", "tests_md")


def block(kind, label, field, **extra):
    out = {"type": kind, "label": label, "field": field, **extra}
    if field in OPTIONAL_FIELDS:
        out["show_if"] = {"field": field, "present": True}
    return out


def gated(value, label, text):
    return {
        "value": value,
        "label": label,
        "help": text,
        "enabled_if": {"field": "evidence_status", "equals": "recovered"},
        "disabled_reason": "Needs recovered evidence.",
    }


def corrected(name, label, kind="text"):
    out = {"name": name, "label": label, "type": kind}
    if kind == "integer":
        out["min"] = 1
    if name in {"title", "language", "framework", "category", "path", "start_line", "end_line"}:
        out["placeholder_field"] = name
    return out


def build_workflow(item):
    properties = {}
    for key in item:
        if key in {"start_line", "end_line"}:
            properties[key] = LINE
        elif key == "fixture_sha256":
            properties[key] = DIGEST
        elif key == "evidence_status":
            properties[key] = {"enum": ["recovered", "missing"]}
        else:
            properties[key] = OPTIONAL if key in OPTIONAL_FIELDS else STRING
    return {
        "schema_version": "1",
        "id": "mergecraft-golden-b002",
        "version": 2,
        "title": "mergeCraft golden batch 002 adjudication",
        "description": (
            "A human confirms, corrects, or abstains on each agent-proposed finding, "
            "judged against the committed fixtures."
        ),
        "item": {
            "id_field": "case_id",
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [key for key in item if key not in OPTIONAL_FIELDS],
                "properties": properties,
            },
        },
        "display": {
            "eyebrow": "{review_id} · {case_id}",
            "blocks": [
                {"type": "heading", "field": "title"},
                {
                    "type": "callout",
                    "tone": "neutral",
                    "text": (
                        "Agent-proposed finding, pending human adjudication. Upstream tests "
                        "were inspected, not run."
                    ),
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
                        {"label": "Fixture", "field": "fixture_path", "style": "mono"},
                    ],
                },
                block("text", "When it happens", "trigger"),
                block("text", "Proposed finding", "finding"),
                block("markdown", "Code at the claimed location (introducing merge)", "buggy_md"),
                block("link", "Pinned source", "source_url"),
                block(
                    "diff",
                    "Introducing diff",
                    "introducing_patch",
                    highlight={
                        "path_field": "path",
                        "start_field": "start_line",
                        "end_field": "end_line",
                    },
                ),
                block("markdown", "Related code", "related_md"),
                block("markdown", "Upstream evidence", "history_md"),
                block("markdown", "Fix PR description (saved snapshot)", "fix_pr_body_md"),
                block("text", "What the fix changed", "correction"),
                block("diff", "Fix diff", "fix_patch"),
                block("markdown", "Code after the fix", "fixed_md"),
                block("text", "Test evidence", "test_evidence"),
                block("markdown", "Regression test", "tests_md"),
                block("markdown", "Limits", "limits_md"),
            ],
        },
        "question": {
            "text": "Did the introducing change cause the described behavior at the cited lines?",
            "help": (
                "Confirm accepts the finding and its stated scope. Choose Correct if it is real "
                "but a field is wrong. Abstain if the evidence does not let you decide."
            ),
        },
        "form": {
            "fields": [
                {
                    "name": "decision",
                    "label": "Decision",
                    "type": "choice",
                    "required": True,
                    "options": [
                        gated("confirm", "Confirm", "The finding and its stated scope hold."),
                        gated("correct", "Correct", "The finding is real but a field is wrong."),
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
                        corrected("title", "Title"),
                        corrected("language", "Language"),
                        corrected("framework", "Framework"),
                        corrected("category", "Category"),
                        corrected("kind", "Kind"),
                        corrected("path", "Path"),
                        corrected("start_line", "Start line", "integer"),
                        corrected("end_line", "End line", "integer"),
                        corrected("notes", "Notes, including a changed claim", "textarea"),
                    ],
                },
            ]
        },
        "output": {
            "format": "json",
            "include": "answered",
            "envelope": {
                key: {"source_meta": key}
                for key in ("schema_version", "batch_id", "adjudicator_login")
            },
            "records_key": "cases",
            "record": {
                **{key: {"item": key} for key in MANIFEST_FIELDS},
                "decision": {"answer": "decision"},
                "decided_at": {"response": "submitted_at"},
                "decided_by": {"response": "user"},
                "corrected_fields": {"answer": "corrected_fields", "empty_as": None},
            },
        },
    }


def main():
    manifest = json.loads((ADJUDICATION / f"{BATCH}.json").read_text(encoding="utf-8"))
    sections = read_sections()
    if len(sections) != len(manifest["cases"]):
        fail(f"packet has {len(sections)} cases, manifest has {len(manifest['cases'])}")
    items = [
        build_item(review_id, row, sections[review_id])
        for review_id, row in zip(sections, manifest["cases"], strict=True)
    ]
    source = {
        "schema_version": "1",
        "source_id": f"{BATCH}-fixtures",
        "title": "mergeCraft golden batch 002 (published fixtures)",
        "workflow": build_workflow(items[0]),
        "meta": {key: manifest[key] for key in ("schema_version", "batch_id", "adjudicator_login")},
        "items": items,
    }
    out = Path(__file__).with_name(f"{BATCH}.source.json")
    out.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {out.relative_to(ROOT)} ({len(items)} items)\n")


if __name__ == "__main__":
    main()
