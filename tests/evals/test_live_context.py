"""#220 — the live corpus review must run with the case's real repo context.

RED suite for PR EV1 (sub-wave EV1.1; implementation EV1.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

Today the production ``ReviewFn`` (``_default_review_fn``) runs ``diff-review``
in a fresh *empty* scratch directory per case, so the reviewer sees none of the
case's pre-patch files — the live corpus review loses all repo context (#220).
EV1.2 adds a materialize-case-repo step:

* A detection case may carry a ``repo/`` subtree next to its patch and
  ``baseline.json`` — the case's pre-patch file tree.
* ``materialize_case_repo(case, dest) -> Path`` (new in ``evals/live_run.py``)
  copies that tree into ``dest`` and returns it.
* The production live path materializes the repo *before* invoking the review,
  and the review's ``cwd`` is the materialized tree — never the empty scratch
  directory and never the corpus checkout itself.

The new ``materialize_case_repo`` symbol is imported lazily inside the test so
collection stays clean while the symbol does not exist yet (per the EV1.1
brief). The wiring test needs no live provider: the review itself is stubbed at
the ``mergecraft.offline_review.run_offline_diff_review`` boundary, so
``skipped: no live gate`` does not apply to this file either.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mergecraft.evals.live_run import (
    BASELINE_FILENAME,
    discover_detection_cases,
    run_detection,
)

_XFAIL_EV1_2 = pytest.mark.xfail(
    reason="green after EV1.2: materialize the case repo before the live review (#220)",
    strict=False,
)

_REPO_A_PY = "old\n"


# ── fixtures ──


def _write_detection_case_with_repo(corpus_dir: Path, case_id: str) -> Path:
    """One detection case carrying a ``repo/`` subtree (the pre-patch file tree).

    The patch touches ``src/a.py``; the repo tree holds that file's pre-patch
    content — exactly the context #220 says the reviewer must see.
    """
    case_dir = corpus_dir / case_id
    repo_dir = case_dir / "repo"
    (repo_dir / "src").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "a.py").write_text(_REPO_A_PY, encoding="utf-8")
    (case_dir / "task.patch").write_text(
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    (case_dir / BASELINE_FILENAME).write_text(
        json.dumps({"closed_world": True, "issues": []}),
        encoding="utf-8",
    )
    return case_dir


# ── #220: materialization contract ──


@_XFAIL_EV1_2
def test_live_review_runs_with_real_repo_context(tmp_path: Path) -> None:
    """The materialized review cwd contains the case's repo files — it is never
    an empty scratch directory."""
    from mergecraft.evals.live_run import materialize_case_repo

    corpus = tmp_path / "corpus"
    _write_detection_case_with_repo(corpus, "bench-detect-repo-001")
    case = discover_detection_cases(corpus)[0]

    review_cwd = materialize_case_repo(case, tmp_path / "review-cwd")

    assert review_cwd.is_dir()
    assert any(review_cwd.iterdir()), "review cwd must not be an empty scratch directory (#220)"
    assert (review_cwd / "src" / "a.py").read_text(encoding="utf-8") == _REPO_A_PY


@_XFAIL_EV1_2
def test_case_repo_is_materialized_before_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordering contract: at the moment the review runs, its cwd *already*
    contains the materialized case repo — materialization happens before the
    review on the production default path (``review_fn=None``), not after and
    not never."""
    import mergecraft.offline_review as offline_mod

    corpus = tmp_path / "corpus"
    _write_detection_case_with_repo(corpus, "bench-detect-repo-001")

    observed: dict[str, Any] = {}

    def _snapshot_cwd(cwd: Path, json_path: Path) -> None:
        """Sync FS helper — keeps blocking pathlib I/O out of the async stub."""
        repo_file = cwd / "src" / "a.py"
        observed["repo_file_at_review_time"] = repo_file.is_file()
        observed["repo_content_at_review_time"] = (
            repo_file.read_text(encoding="utf-8") if repo_file.is_file() else None
        )
        json_path.write_text(json.dumps({"findings": []}), encoding="utf-8")

    async def _fake_review(**kwargs: Any) -> SimpleNamespace:
        _snapshot_cwd(Path(kwargs["cwd"]), Path(kwargs["json_path"]))
        return SimpleNamespace(success=True, error=None)

    monkeypatch.setattr(offline_mod, "run_offline_diff_review", _fake_review)
    monkeypatch.setattr(
        "mergecraft.evals.live_run.has_credentials_for_slug",
        lambda _model: True,
    )

    metrics, skipped_reason = run_detection(
        provider="claude",
        model="claude-sonnet-5",
        corpus_dir=corpus,
        results_dir=tmp_path / "results",
        review_fn=None,  # the production default path — the locus of #220
    )

    assert metrics is not None
    assert skipped_reason is None
    assert observed["repo_file_at_review_time"] is True
    assert observed["repo_content_at_review_time"] == _REPO_A_PY
