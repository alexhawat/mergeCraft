"""The files API omits executable-bit changes; trees must supply that proof."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.config.settings import FastPathSettings
from mergecraft.fast_path import decide_fast_path
from tests.review.test_fast_path_gate import FakeScm

HEAD = "c" * 40
BASE = "b" * 40


class ModeScm(FakeScm):
    def __init__(
        self, *, before_mode: str = "100644", after_mode: str = "100644", problem: str = ""
    ) -> None:
        super().__init__(
            files=[
                {
                    "filename": "run.py",
                    "additions": 1,
                    "deletions": 1,
                    "patch": "@@ -1 +1 @@\n-x = 1   \n+x = 1",
                }
            ],
            contents={"run.py": "x = 1\n"},
        )
        self.modes = {BASE: before_mode, HEAD: after_mode}
        self.problem = problem
        self.refs: list[str] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if "/contents/" in path:
            assert params == {"ref": HEAD}
        if path.endswith("/pulls/7"):
            return {
                "base": {"sha": BASE},
                "head": {"sha": "d" * 40 if self.problem == "moved-head" else HEAD},
            }
        if "/git/trees/" in path:
            sha = path.rsplit("/", 1)[-1]
            self.refs.append(sha)
            assert sha in {BASE, HEAD}
            assert params == {"recursive": "1"}
            if self.problem == "missing-tree":
                return {}
            rows = [{"path": "run.py", "mode": self.modes[sha], "type": "blob"}]
            if self.problem == "missing-path":
                rows = []
            return {"tree": rows, "truncated": self.problem == "truncated"}
        return await super().get(path, params)


@pytest.mark.parametrize(
    ("before_mode", "after_mode", "expected"),
    [
        ("100644", "100644", "skip"),
        ("100755", "100755", "skip"),
        ("100755", "100644", "full"),
        ("100644", "100755", "full"),
        ("120000", "120000", "full"),
    ],
)
async def test_api_patch_requires_unchanged_regular_file_modes(
    before_mode: str, after_mode: str, expected: str
) -> None:
    scm = ModeScm(before_mode=before_mode, after_mode=after_mode)
    decision = await decide_fast_path(
        scm,
        "acme",
        "demo",
        7,
        HEAD,  # type: ignore[arg-type]
        config=FastPathSettings(enabled=True, skip_llm=["whitespace"]),
        operator_owned=True,
    )
    assert decision.tier == expected
    if expected == "skip":
        assert scm.refs == [BASE, HEAD]


@pytest.mark.parametrize("problem", ["missing-tree", "missing-path", "truncated", "moved-head"])
async def test_unavailable_or_stale_mode_proof_falls_back_to_full(problem: str) -> None:
    scm = ModeScm(problem=problem)
    decision = await decide_fast_path(
        scm,
        "acme",
        "demo",
        7,
        HEAD,  # type: ignore[arg-type]
        config=FastPathSettings(enabled=True, skip_llm=["whitespace"]),
        operator_owned=True,
    )
    assert decision.tier == "full"
