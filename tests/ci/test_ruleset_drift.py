"""Ruleset drift check: live rulesets vs the committed expectation (#1298).

Fixtures mirror the real ``GET /repos/{owner}/{repo}/rulesets[/{id}]`` payloads.
Nothing here touches the network: the fetcher is injected.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT

REPOSITORY = "alexhawat/mergeCraft"
_CHECKS = ["Verify (static + build py3.11)", "Verify (tests py3.11 1/2)", "mergecraft review"]


def _module(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    return importlib.import_module("check_ruleset_drift")


def _live_rulesets() -> list[dict[str, Any]]:
    """Detail payloads shaped like the real API, volatile fields included."""
    return [
        {
            "id": 19969460,
            "name": "protect-main",
            "target": "branch",
            "source_type": "Repository",
            "source": REPOSITORY,
            "enforcement": "active",
            "conditions": {
                "ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH", "refs/heads/pre-0.0.1"]}
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 1,
                        "dismiss_stale_reviews_on_push": True,
                        "required_reviewers": [],
                        "require_code_owner_review": True,
                        "require_last_push_approval": True,
                        "required_review_thread_resolution": True,
                        "allowed_merge_methods": ["merge", "squash", "rebase"],
                    },
                },
            ],
            "node_id": "RRS_lACqUmVwb3NpdG9yec5OVjuBzgEwtbQ",
            "created_at": "2026-07-29T14:07:51.620+02:00",
            "updated_at": "2026-07-29T14:26:25.820+02:00",
            "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole"}],
            "current_user_can_bypass": "always",
            "_links": {"self": {"href": "https://api.github.com/x"}},
        },
        {
            "id": 21652574,
            "name": "require-ci-on-main",
            "target": "branch",
            "source_type": "Repository",
            "source": REPOSITORY,
            "enforcement": "active",
            "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
            "rules": [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": True,
                        "do_not_enforce_on_create": False,
                        "required_status_checks": [
                            {"context": c, **({"integration_id": 15368} if "review" in c else {})}
                            for c in _CHECKS
                        ],
                    },
                }
            ],
            "node_id": "RRS_lACqUmVwb3NpdG9yec5OVjuBzgFKZF4",
            "created_at": "2026-08-27T15:04:44.980+02:00",
            "updated_at": "2026-11-12T19:35:07.879+01:00",
            "bypass_actors": [],
            "current_user_can_bypass": "never",
            "_links": {"self": {"href": "https://api.github.com/y"}},
        },
    ]


def _fetcher(rulesets: list[dict[str, Any]]) -> Any:
    calls: list[str] = []

    def fetch(path: str) -> Any:
        calls.append(path)
        listing = f"repos/{REPOSITORY}/rulesets"
        if path == listing:
            return [{"id": r["id"], "name": r["name"]} for r in rulesets]
        for ruleset in rulesets:
            if path == f"{listing}/{ruleset['id']}":
                return ruleset
        raise AssertionError(f"unexpected API path {path}")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _ci_ruleset(rulesets: list[dict[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in rulesets if r["name"] == "require-ci-on-main")
    return found


def _checks_params(rulesets: list[dict[str, Any]]) -> dict[str, Any]:
    params: dict[str, Any] = _ci_ruleset(rulesets)["rules"][0]["parameters"]
    return params


def _workflows(tmp_path: Path) -> Path:
    directory = tmp_path / "workflows"
    directory.mkdir()
    (directory / "ci.yml").write_text(
        "jobs:\n"
        "  static:\n"
        "    name: Verify (static + build py${{ matrix.python }})\n"
        "    strategy:\n"
        "      matrix:\n"
        '        python: ["3.11"]\n'
        "  test:\n"
        "    name: Verify (tests py${{ matrix.python }} ${{ matrix.group }}/2)\n"
        "    strategy:\n"
        "      matrix:\n"
        '        python: ["3.11"]\n'
        "        group: [1, 2]\n"
        "  gate:\n"
        "    name: mergecraft review\n",
        encoding="utf-8",
    )
    return directory


def _run(
    module: Any,
    tmp_path: Path,
    live: list[dict[str, Any]],
    expected_rulesets: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps(module.normalize_rulesets(expected_rulesets)), encoding="utf-8")
    code = module.main(
        [
            "--check",
            *("--repo", REPOSITORY),
            *("--expected", str(expected)),
            *("--workflows", str(_workflows(tmp_path))),
        ],
        fetch=_fetcher(live),
    )
    return code, capsys.readouterr().err


def _drop_check(rulesets: list[dict[str, Any]]) -> None:
    _checks_params(rulesets)["required_status_checks"].pop(0)


def _add_check(rulesets: list[dict[str, Any]]) -> None:
    _checks_params(rulesets)["required_status_checks"].append({"context": "Extra job"})


def _strict_off(rulesets: list[dict[str, Any]]) -> None:
    _checks_params(rulesets)["strict_required_status_checks_policy"] = False


def _set_enforcement(value: str) -> Any:
    def mutate(rulesets: list[dict[str, Any]]) -> None:
        _ci_ruleset(rulesets)["enforcement"] = value

    return mutate


def _remove_ruleset(rulesets: list[dict[str, Any]]) -> None:
    rulesets[:] = [r for r in rulesets if r["name"] != "require-ci-on-main"]


def _drop_deletion_rule(rulesets: list[dict[str, Any]]) -> None:
    rulesets[0]["rules"] = [r for r in rulesets[0]["rules"] if r["type"] != "deletion"]


def _review_count_zero(rulesets: list[dict[str, Any]]) -> None:
    rulesets[0]["rules"][2]["parameters"]["required_approving_review_count"] = 0


def _drop_integration_id(rulesets: list[dict[str, Any]]) -> None:
    for check in _checks_params(rulesets)["required_status_checks"]:
        check.pop("integration_id", None)


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        pytest.param(_drop_check, "required check removed: 'Verify (static", id="check-removed"),
        pytest.param(_add_check, "unexpected extra required check: 'Extra job'", id="check-added"),
        pytest.param(_strict_off, "strict_required_status_checks_policy", id="strict-off"),
        pytest.param(_set_enforcement("disabled"), "enforcement is 'disabled'", id="disabled"),
        pytest.param(_set_enforcement("evaluate"), "enforcement is 'evaluate'", id="evaluate"),
        pytest.param(_remove_ruleset, "require-ci-on-main: ruleset missing live", id="missing"),
        pytest.param(_drop_deletion_rule, "rule deletion: missing live", id="rule-removed"),
        pytest.param(_review_count_zero, "required_approving_review_count", id="review-count"),
        pytest.param(_drop_integration_id, "integration_id is None", id="integration-id"),
    ],
)
def test_drift_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutate: Any,
    needle: str,
) -> None:
    module = _module(monkeypatch)
    live = _live_rulesets()
    mutate(live)
    code, err = _run(module, tmp_path, live, _live_rulesets(), capsys)
    assert code == 1
    assert needle in err
    assert "--write" in err


def test_no_drift_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module(monkeypatch)
    code, err = _run(module, tmp_path, _live_rulesets(), _live_rulesets(), capsys)
    assert code == 0
    assert err == ""


def test_unexpected_live_ruleset_is_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    live = _live_rulesets()
    expected = module.normalize_rulesets(live[:1])
    lines = module.diff_expectation(expected, module.normalize_rulesets(live))
    assert lines == ["require-ci-on-main: unexpected live ruleset not in the expectation"]


def test_ordering_differences_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    shuffled = copy.deepcopy(_live_rulesets())
    shuffled.reverse()
    for ruleset in shuffled:
        ruleset["rules"].reverse()
        ruleset["conditions"]["ref_name"]["include"].reverse()
    _checks_params(shuffled)["required_status_checks"].reverse()
    base = module.normalize_rulesets(_live_rulesets())
    assert module.normalize_rulesets(shuffled) == base
    assert module.diff_expectation(base, module.normalize_rulesets(shuffled)) == []


def test_volatile_fields_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    changed = copy.deepcopy(_live_rulesets())
    for ruleset in changed:
        ruleset["id"] += 1
        ruleset["node_id"] = "RRS_other"
        ruleset["created_at"] = "2030-01-01T00:00:00Z"
        ruleset["updated_at"] = "2030-01-02T00:00:00Z"
        ruleset["_links"] = {}
        ruleset["bypass_actors"] = [{"actor_id": 99, "actor_type": "Team"}]
        ruleset["current_user_can_bypass"] = "never"
    base = module.normalize_rulesets(_live_rulesets())
    assert module.diff_expectation(base, module.normalize_rulesets(changed)) == []
    text = json.dumps(base)
    for volatile in ("node_id", "created_at", "_links", "bypass_actors", "19969460"):
        assert volatile not in text


def test_fetch_only_reads_ruleset_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    fetch = _fetcher(_live_rulesets())
    module.fetch_live_rulesets(REPOSITORY, fetch)
    assert fetch.calls == [
        f"repos/{REPOSITORY}/rulesets",
        f"repos/{REPOSITORY}/rulesets/19969460",
        f"repos/{REPOSITORY}/rulesets/21652574",
    ]


def test_write_then_check_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module(monkeypatch)
    expected = tmp_path / "expected.json"
    fetch = _fetcher(_live_rulesets())
    assert (
        module.main(["--write", "--repo", REPOSITORY, "--expected", str(expected)], fetch=fetch)
        == 0
    )
    args = ["--check", "--repo", REPOSITORY, "--expected", str(expected)]
    args += ["--workflows", str(_workflows(tmp_path))]
    assert module.main(args, fetch=fetch) == 0


def test_required_check_without_a_producing_job_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module(monkeypatch)
    live = _live_rulesets()
    _add_check(live)  # both sides agree on "Extra job"; no workflow produces it
    code, err = _run(module, tmp_path, live, live, capsys)
    assert code == 1
    assert "'Extra job' is produced by no workflow job" in err


def test_matrix_names_expand_and_unresolvable_ones_become_patterns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module(monkeypatch)
    directory = tmp_path / "wf"
    directory.mkdir()
    (directory / "a.yml").write_text(
        "jobs:\n"
        "  plain:\n    steps: []\n"
        "  dyn:\n    name: Deploy ${{ inputs.target }}\n"
        "  call:\n    uses: ./.github/workflows/x.yml\n",
        encoding="utf-8",
    )
    exact, patterns = module.produced_check_names(directory)
    assert exact == {"plain"}
    assert [bool(p.match("Deploy prod")) for p in patterns] == [True]
    assert not patterns[0].match("Deploy")


def test_committed_expectation_is_consistent_with_workflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline: the committed file parses, requires the review gate, and is produceable."""
    module = _module(monkeypatch)
    expected = json.loads((REPO_ROOT / ".github" / "rulesets.expected.json").read_text("utf-8"))
    ci = expected["rulesets"]["require-ci-on-main"]["rules"]["required_status_checks"]
    contexts = {c["context"] for c in ci["required_status_checks"]}
    assert ci["strict_required_status_checks_policy"] is True
    assert "mergecraft review" in contexts
    assert module.unproduced_contexts(expected) == []
