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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

    from mergecraft.config.settings import FastPathSettings


_FIXTURES = Path(__file__).resolve().parent.parent / "classify" / "fixtures"
_PIN_DIFF = (_FIXTURES / "pin_bump_pr_889_shape.diff").read_text(encoding="utf-8")
_VERIFIER = "Verify changed deployment candidates"
_HEAD = "c" * 40


def _config(**overrides: Any) -> FastPathSettings:
    from mergecraft.config.settings import FastPathSettings

    base: dict[str, Any] = {
        "enabled": True,
        "skipLlm": ["pinBump", "prose"],
        "pinBump": {"requireChecks": [_VERIFIER]},
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
    ) -> dict[str, Any]:
        self.requests.append(f"checks:{ref}")
        if self._checks_error is not None:
            raise self._checks_error
        return {"check_runs": self._check_runs}


def _passing() -> list[dict[str, Any]]:
    return [{"name": _VERIFIER, "conclusion": "success"}]


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
            {"name": _VERIFIER, "conclusion": "success"},
            {"name": "lint", "conclusion": "failure"},
        ],
    )

    inputs = await load_triage_inputs(scm, "acme", "demo", 7, _HEAD)  # type: ignore[arg-type]

    assert isinstance(inputs, TriageInputs)
    assert "08274dda" in inputs.diff_text
    assert inputs.passed_checks == (_VERIFIER,)


async def test_a_failed_or_pending_verifier_check_does_not_count_as_passed() -> None:
    for conclusion in ("failure", "neutral", None):
        scm = FakeScm(
            files=_files_from_diff(_PIN_DIFF),
            check_runs=[{"name": _VERIFIER, "conclusion": conclusion}],
        )

        assert (await _decide(scm)).tier == "full"


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
