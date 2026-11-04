"""The pre-dispatch gate: a verified mechanical diff never reaches the LLM.

Triage reads the pull request's diff through the files API, the head-side text of any
prose file it must prove stays out of a code fence, and the checks that passed on the
head SHA — and decides before the MCP server and the agent exist. Every failure to
read, every truncation, every file GitHub sent no patch for, and every config that is
not the operator's base-side config decides ``full``: the gate may only ever spend less
when it is certain, never skip because it could not tell.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from mergecraft.scm.types import ListedItems

if TYPE_CHECKING:
    from mergecraft.config.settings import FastPathSettings
    from mergecraft.scm.protocol import ScmProvider


_FIXTURES = Path(__file__).resolve().parent.parent / "classify" / "fixtures"
_PIN_DIFF = (_FIXTURES / "pin_bump_pr_889_shape.diff").read_text(encoding="utf-8")
_VERIFIER = "Verify changed deployment candidates"
_TRUSTED_APP = "mergecraft-reviewer"
_HEAD = "c" * 40


def _config(**overrides: Any) -> FastPathSettings:
    from mergecraft.config.settings import FastPathSettings

    base: dict[str, Any] = {
        "enabled": True,
        "skipLlm": ["pinBump", "prose"],
        "pinBump": {"requireChecks": [_VERIFIER], "trustedCheckApps": [_TRUSTED_APP]},
    }
    base.update(overrides)
    return FastPathSettings.model_validate(base)


def _files_from_diff(diff: str) -> list[dict[str, Any]]:
    """Split a unified diff into files-API entries (filename + patch)."""
    entries: list[dict[str, Any]] = []
    for chunk in diff.split("diff --git ")[1:]:
        header, _, rest = chunk.partition("\n")
        path = header.split(" b/", 1)[1]
        patch = "@@" + rest.split("@@", 1)[1] if "@@" in rest else ""
        added = sum(1 for ln in patch.splitlines() if ln.startswith("+"))
        removed = sum(1 for ln in patch.splitlines() if ln.startswith("-"))
        entries.append({"filename": path, "additions": added, "deletions": removed, "patch": patch})
    return entries


class FakeScm:
    """Answers the files API, the check-run listing and the contents API."""

    def __init__(
        self,
        *,
        files: list[dict[str, Any]],
        check_runs: list[dict[str, Any]] | None = None,
        contents: dict[str, str] | None = None,
        files_error: Exception | None = None,
        checks_error: Exception | None = None,
    ) -> None:
        self._files = files
        self._check_runs = check_runs if check_runs is not None else []
        self._contents = contents or {}
        self._files_error = files_error
        self._checks_error = checks_error
        self.requests: list[str] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.requests.append(path)
        params = params or {}
        if path.endswith("/files"):
            if self._files_error is not None:
                raise self._files_error
            page = int(params.get("page", 1))
            per_page = int(params.get("per_page", 100))
            return self._files[(page - 1) * per_page : page * per_page]
        if "/contents/" in path:
            name = path.split("/contents/", 1)[1]
            if name not in self._contents:
                msg = f"404 {name}"
                raise RuntimeError(msg)
            raw = self._contents[name].encode()
            return {"encoding": "base64", "content": base64.b64encode(raw).decode()}
        return {}

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **_kwargs: Any
    ) -> ListedItems:
        self.requests.append(f"checks:{ref}")
        if self._checks_error is not None:
            raise self._checks_error
        return ListedItems(items=self._check_runs, incomplete=False)


def _check(
    name: str, conclusion: str | None = "success", *, app: str | None = _TRUSTED_APP
) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "conclusion": conclusion}
    if app is not None:
        row["app"] = {"slug": app}
    return row


def _passing() -> list[dict[str, Any]]:
    return [_check(_VERIFIER)]


async def _decide(scm: FakeScm, **kwargs: Any) -> Any:
    from mergecraft.fast_path import decide_fast_path

    options: dict[str, Any] = {"config": _config(), "operator_owned": True}
    options.update(kwargs)
    return await decide_fast_path(scm, "acme", "demo", 7, _HEAD, **options)  # type: ignore[arg-type]


async def test_a_verified_pin_bump_is_skipped() -> None:
    scm = FakeScm(files=_files_from_diff(_PIN_DIFF), check_runs=_passing())

    decision = await _decide(scm)

    assert decision.tier == "skip"
    assert decision.recognizer == "pinBump"
    assert decision.relied_on_checks == (_VERIFIER,)


async def test_the_inputs_are_the_diff_the_head_text_and_the_passed_checks() -> None:
    from mergecraft.classify.triage import TriageInputs
    from mergecraft.fast_path import load_triage_inputs

    scm = FakeScm(
        files=_files_from_diff(_PIN_DIFF),
        check_runs=[
            _check(_VERIFIER),
            _check("lint", "failure"),
        ],
    )

    inputs = await load_triage_inputs(
        scm,
        "acme",
        "demo",
        7,
        _HEAD,
        trusted_apps=[_TRUSTED_APP],  # type: ignore[arg-type]
    )

    assert isinstance(inputs, TriageInputs)
    assert "08274dda" in inputs.diff_text
    assert inputs.passed_checks == (_VERIFIER,)


async def test_a_failed_or_pending_verifier_check_does_not_count_as_passed() -> None:
    for conclusion in ("failure", "neutral", None):
        scm = FakeScm(
            files=_files_from_diff(_PIN_DIFF),
            check_runs=[_check(_VERIFIER, conclusion)],
        )

        assert (await _decide(scm)).tier == "full"


async def test_a_same_named_success_from_another_app_is_not_verification() -> None:
    """A check-run name is set by its creator; only the configured App can vouch."""
    scm = FakeScm(
        files=_files_from_diff(_PIN_DIFF),
        check_runs=[_check(_VERIFIER, app="some-other-app")],
    )

    decision = await _decide(scm)

    assert decision.tier == "full"
    assert _VERIFIER in decision.reason


async def test_a_same_named_success_with_no_app_identity_is_not_verification() -> None:
    scm = FakeScm(
        files=_files_from_diff(_PIN_DIFF),
        check_runs=[_check(_VERIFIER, app=None)],
    )

    assert (await _decide(scm)).tier == "full"


async def test_the_actions_app_cannot_vouch_even_when_configured() -> None:
    """A `pull_request` workflow's job names come from the head ref."""
    scm = FakeScm(
        files=_files_from_diff(_PIN_DIFF),
        check_runs=[_check(_VERIFIER, app="github-actions")],
    )

    decision = await _decide(
        scm,
        config=_config(
            pinBump={"requireChecks": [_VERIFIER], "trustedCheckApps": ["github-actions"]}
        ),
    )

    assert decision.tier == "full"
    assert "trustedCheckApps" in decision.reason


async def test_a_pin_bump_with_no_trusted_app_never_skips() -> None:
    scm = FakeScm(files=_files_from_diff(_PIN_DIFF), check_runs=_passing())

    decision = await _decide(scm, config=_config(pinBump={"requireChecks": [_VERIFIER]}))

    assert decision.tier == "full"
    assert "trustedCheckApps" in decision.reason


async def test_a_disabled_fast_path_makes_no_request_at_all() -> None:
    from mergecraft.config.settings import FastPathSettings

    scm = FakeScm(files=_files_from_diff(_PIN_DIFF), check_runs=_passing())

    decision = await _decide(scm, config=FastPathSettings())

    assert decision.tier == "full"
    assert scm.requests == []


async def test_config_that_is_not_the_operators_base_side_config_is_ignored() -> None:
    """A fork author controls the head-side config; it can never opt a PR out of review."""
    scm = FakeScm(files=_files_from_diff(_PIN_DIFF), check_runs=_passing())

    decision = await _decide(scm, operator_owned=False)

    assert decision.tier == "full"
    assert "base" in decision.reason.lower()
    assert scm.requests == []


async def test_a_files_api_failure_is_full_never_skip() -> None:
    scm = FakeScm(files=[], check_runs=_passing(), files_error=RuntimeError("502"))

    decision = await _decide(scm)

    assert decision.tier == "full"
    assert "502" in decision.reason or "files" in decision.reason.lower()


async def test_a_check_listing_failure_is_full_never_skip() -> None:
    scm = FakeScm(
        files=_files_from_diff(_PIN_DIFF), checks_error=RuntimeError("503"), check_runs=[]
    )

    assert (await _decide(scm)).tier == "full"


async def test_a_file_github_sent_no_patch_for_is_full() -> None:
    files = _files_from_diff(_PIN_DIFF)
    files.append({"filename": "src/huge.py", "additions": 900, "deletions": 1, "patch": None})
    scm = FakeScm(files=files, check_runs=_passing())

    assert (await _decide(scm)).tier == "full"


async def test_a_truncated_files_listing_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft import fast_path

    page = [
        {"filename": f"f{n}.md", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+x\n"}
        for n in range(100)
    ]
    scm = FakeScm(files=page * 3, check_runs=_passing())
    monkeypatch.setattr(fast_path, "_FILES_MAX_PAGES", 2)

    decision = await _decide(scm)

    assert decision.tier == "full"
    assert "truncat" in decision.reason.lower() or "page" in decision.reason.lower()


async def test_an_empty_pull_request_is_full() -> None:
    assert (await _decide(FakeScm(files=[], check_runs=_passing()))).tier == "full"


async def test_a_prose_edit_reads_the_head_text_and_skips() -> None:
    files = [
        {
            "filename": "README.md",
            "additions": 1,
            "deletions": 1,
            "patch": "@@ -1,3 +1,3 @@\n # Title\n-Old words.\n+New words.\n More.\n",
        }
    ]
    scm = FakeScm(files=files, contents={"README.md": "# Title\nNew words.\nMore.\n"})

    decision = await _decide(scm)

    assert decision.tier == "skip"
    assert decision.recognizer == "prose"
    assert any("/contents/README.md" in request for request in scm.requests)


async def test_a_prose_edit_whose_head_text_cannot_be_read_is_full() -> None:
    files = [
        {
            "filename": "README.md",
            "additions": 1,
            "deletions": 1,
            "patch": "@@ -1,3 +1,3 @@\n # Title\n-Old words.\n+New words.\n More.\n",
        }
    ]

    assert (await _decide(FakeScm(files=files, contents={}))).tier == "full"


# ── renames and copies name their source ──────────────────────────────────────
#
# GitHub reports a rename as ``previous_filename`` on the files-API entry, not in the
# patch. A diff rebuilt from ``filename`` alone shows a rename as an in-place edit of
# the new name, so path recognizers and the prose gate's suffix check miss the source.

_PROSE_PATCH = "@@ -1,3 +1,3 @@\n # Title\n-Old words.\n+New words.\n More.\n"


def _renamed(previous: str, name: str, *, status: str = "renamed") -> dict[str, Any]:
    return {
        "filename": name,
        "previous_filename": previous,
        "status": status,
        "additions": 1,
        "deletions": 1,
        "patch": _PROSE_PATCH,
    }


async def _read(scm: FakeScm) -> tuple[str, list[str]]:
    from mergecraft.fast_path import _read_diff

    # This fake supplies the get method used by _read_diff, not the full SCM API.
    return await _read_diff(cast("ScmProvider", scm), "acme", "demo", 7)


async def test_a_rename_is_written_the_way_git_writes_it() -> None:
    from mergecraft.review_policy.ignore_paths import rename_sources

    diff, paths = await _read(FakeScm(files=[_renamed("src/auth.py", "docs/notes.md")]))

    assert diff.startswith(
        "diff --git a/src/auth.py b/docs/notes.md\n"
        "rename from src/auth.py\n"
        "rename to docs/notes.md\n"
        "@@ -1,3 +1,3 @@\n"
    )
    assert paths == ["docs/notes.md", "src/auth.py"]
    # The rebuilt header is compatible with the shared rename reader.
    assert rename_sources(diff) == {"docs/notes.md": "src/auth.py"}


async def test_a_copy_is_labelled_a_copy() -> None:
    diff, paths = await _read(FakeScm(files=[_renamed("docs/a.md", "docs/b.md", status="copied")]))

    assert "diff --git a/docs/a.md b/docs/b.md\ncopy from docs/a.md\ncopy to docs/b.md\n" in diff
    assert paths == ["docs/b.md", "docs/a.md"]


async def test_an_in_place_edit_keeps_the_plain_header() -> None:
    files = [{"filename": "README.md", "additions": 1, "deletions": 1, "patch": _PROSE_PATCH}]

    diff, paths = await _read(FakeScm(files=files))

    assert diff.startswith("diff --git a/README.md b/README.md\n@@ ")
    assert "rename" not in diff
    assert paths == ["README.md"]


async def test_a_code_file_renamed_into_prose_is_never_a_prose_skip() -> None:
    """The pre-image was code; a rename into ``docs/`` does not make it a prose edit."""
    scm = FakeScm(
        files=[_renamed("src/auth.py", "docs/notes.md")],
        contents={"docs/notes.md": "# Title\nNew words.\nMore.\n"},
    )

    decision = await _decide(scm)

    assert decision.tier == "full"
    assert decision.recognizer is None


@pytest.mark.parametrize("status", ["renamed", "copied"])
@pytest.mark.parametrize(
    ("previous", "name", "recognizer"),
    [
        ("AGENTS.md", "docs/notes.md", "prose"),
        (".github/skills/code-review/SKILL.md", "docs/notes.md", "prose"),
        ("billing/notes.md", "docs/notes.md", "prose"),
        ("src/auth.py", "generated/auth.py", "generated"),
    ],
)
async def test_a_refused_source_cannot_skip_by_changing_its_name(
    previous: str, name: str, recognizer: str, status: str
) -> None:
    scm = FakeScm(
        files=[_renamed(previous, name, status=status)],
        contents={name: "# Title\nNew words.\nMore.\n"},
    )

    decision = await _decide(scm, config=_config(skipLlm=[recognizer]))

    assert decision.tier == "full"
    assert decision.recognizer is None


@pytest.mark.parametrize("status", ["renamed", "copied"])
async def test_a_safe_prose_move_still_skips(status: str) -> None:
    scm = FakeScm(
        files=[_renamed("docs/old.md", "docs/new.md", status=status)],
        contents={"docs/new.md": "# Title\nNew words.\nMore.\n"},
    )

    decision = await _decide(scm, config=_config(skipLlm=["prose"]))

    assert decision.tier == "skip"
    assert decision.recognizer == "prose"
