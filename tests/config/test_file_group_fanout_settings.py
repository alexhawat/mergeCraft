"""``review.fileGroupFanout`` — the setting that turns file-group fan-out on.

Off by default, sequential by default, bounded group count and concurrency,
camelCase aliases on the wire, unknown keys rejected like every other
``review.*`` block. The repository's own ``.mergecraft/config.yaml`` keeps it
off until a live large-PR run has validated group prompts and aggregation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import ReviewSettings, load_repo_settings
from tests.cli.support_agent_roster import DEFAULT_MODELS_YAML, write_config

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "max_groups": 6,
    "min_diff_lines": 800,
    "min_files": 20,
    "binding": None,
    "concurrency": 1,
    "per_group_timeout_s": 600,
}

_WIRE: dict[str, Any] = {
    "enabled": True,
    "maxGroups": 3,
    "minDiffLines": 400,
    "minFiles": 10,
    "binding": "reviewer2",
    "concurrency": 2,
    "perGroupTimeoutS": 300,
}


def _settings_model() -> Any:
    from mergecraft.config import settings as settings_module

    model = getattr(settings_module, "FileGroupFanoutSettings", None)
    if model is None:
        pytest.fail("mergecraft.config.settings.FileGroupFanoutSettings is not implemented")
    return model


def _fanout(review: ReviewSettings) -> Any:
    fanout = getattr(review, "file_group_fanout", None)
    if fanout is None:
        pytest.fail("ReviewSettings.file_group_fanout is not implemented")
    return fanout


def _as_fields(fanout: Any) -> dict[str, Any]:
    return {name: getattr(fanout, name) for name in _DEFAULTS}


def test_review_settings_default_fanout_is_off_and_sequential() -> None:
    fanout = _fanout(ReviewSettings())

    assert isinstance(fanout, _settings_model())
    assert _as_fields(fanout) == _DEFAULTS


def test_standalone_model_defaults_match_the_review_default() -> None:
    assert _as_fields(_settings_model()()) == _DEFAULTS


def test_camel_case_aliases_populate_every_field() -> None:
    review = ReviewSettings.model_validate({"fileGroupFanout": _WIRE})

    assert _as_fields(_fanout(review)) == {
        "enabled": True,
        "max_groups": 3,
        "min_diff_lines": 400,
        "min_files": 10,
        "binding": "reviewer2",
        "concurrency": 2,
        "per_group_timeout_s": 300,
    }


def test_field_names_populate_too() -> None:
    review = ReviewSettings.model_validate(
        {"file_group_fanout": {"enabled": True, "max_groups": 2, "per_group_timeout_s": 90}}
    )

    fanout = _fanout(review)
    assert fanout.enabled is True
    assert fanout.max_groups == 2
    assert fanout.per_group_timeout_s == 90


def test_dump_by_alias_round_trips() -> None:
    review = ReviewSettings.model_validate({"fileGroupFanout": _WIRE})

    dumped = review.model_dump(by_alias=True)

    assert dumped["fileGroupFanout"] == _WIRE
    assert ReviewSettings.model_validate(dumped) == review


@pytest.mark.parametrize(
    ("key", "value", "error_type"),
    [
        pytest.param("maxGroups", 0, "greater_than_equal", id="max-groups-below-1"),
        pytest.param("maxGroups", 13, "less_than_equal", id="max-groups-above-12"),
        pytest.param("concurrency", 0, "greater_than_equal", id="concurrency-below-1"),
        pytest.param("concurrency", 7, "less_than_equal", id="concurrency-above-6"),
        pytest.param("perGroupTimeoutS", 0, "greater_than_equal", id="per-group-timeout-zero"),
        pytest.param("perGroupTimeoutS", -5, "greater_than_equal", id="per-group-timeout-negative"),
        pytest.param("perGroupTimeoutS", 901, "less_than_equal", id="per-group-timeout-above-900"),
    ],
)
def test_out_of_range_bounds_are_rejected_naming_the_field(
    key: str, value: int, error_type: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ReviewSettings.model_validate({"fileGroupFanout": {key: value}})

    errors = [(tuple(error["loc"]), error["type"]) for error in exc_info.value.errors()]
    assert errors == [(("fileGroupFanout", key), error_type)]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("maxGroups", 1, id="max-groups-1"),
        pytest.param("maxGroups", 12, id="max-groups-12"),
        pytest.param("concurrency", 1, id="concurrency-1"),
        pytest.param("concurrency", 6, id="concurrency-6"),
        pytest.param("perGroupTimeoutS", 1, id="per-group-timeout-1"),
        pytest.param("perGroupTimeoutS", 900, id="per-group-timeout-900"),
    ],
)
def test_inclusive_bounds_are_accepted(key: str, value: int) -> None:
    review = ReviewSettings.model_validate({"fileGroupFanout": {key: value}})

    dumped = review.model_dump(by_alias=True)["fileGroupFanout"]
    assert dumped[key] == value


def test_unknown_fanout_key_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ReviewSettings.model_validate({"fileGroupFanout": {"enabled": True, "maxGroup": 3}})

    errors = [(tuple(error["loc"]), error["type"]) for error in exc_info.value.errors()]
    assert errors == [(("fileGroupFanout", "maxGroup"), "extra_forbidden")]


def test_repo_config_yaml_block_loads(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        DEFAULT_MODELS_YAML
        + """
review:
  fileGroupFanout:
    enabled: true
    maxGroups: 4
    minFiles: 12
    binding: reviewer
    concurrency: 2
""",
    )

    fanout = _fanout(load_repo_settings(root=tmp_path).review)

    assert fanout.enabled is True
    assert fanout.max_groups == 4
    assert fanout.min_files == 12
    assert fanout.min_diff_lines == 800
    assert fanout.binding == "reviewer"
    assert fanout.concurrency == 2
    assert fanout.per_group_timeout_s == 600


def test_this_repository_keeps_fanout_off() -> None:
    """The shipped config does not enable fan-out ahead of live validation."""
    fanout = _fanout(load_repo_settings(root=_REPO_ROOT, load_learnings_files=False).review)

    assert fanout.enabled is False
