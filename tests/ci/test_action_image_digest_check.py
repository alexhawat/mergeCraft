"""Unit tests for ``scripts/check_action_image_digest.py`` (#526)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from tests.ci.workflow_support import REPO_ROOT


def _load_module() -> Any:
    path = REPO_ROOT / "scripts" / "check_action_image_digest.py"
    spec = importlib.util.spec_from_file_location("check_action_image_digest", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestGhcrDigestLookup:
    def test_published_sha_tag_has_digest(self) -> None:
        module = _load_module()
        lookup = module._ghcr_digest_for_tag("b34e9f25c5d2dee0e638fa3c62f29733d0fc10c5")
        assert lookup.status == module.TagLookupStatus.FOUND
        assert lookup.digest == (
            "sha256:3765b55ae73a0974d5fa14842bb73e80a347c2f7d66cb8bbfd5394806b6fae58"
        )

    def test_missing_tag_is_not_registry_error(self) -> None:
        module = _load_module()
        lookup = module._ghcr_digest_for_tag("0000000000000000000000000000000000000000")
        assert lookup.status == module.TagLookupStatus.MISSING

    def test_old_published_digest_lacks_tracing_extra(self) -> None:
        module = _load_module()
        config = module._fetch_oci_config_for_tag("cfdf38dcd062779aac3e141c51f134213d395b67")
        assert config is not None
        assert module._image_has_tracing_extra(config) is False


class TestMain:
    def test_fails_when_image_is_dockerfile(self, tmp_path: Path) -> None:
        module = _load_module()
        action = tmp_path / "action.yml"
        action.write_text("runs:\n  using: docker\n  image: Dockerfile\n", encoding="utf-8")
        module.ACTION_YML = action
        assert module.main() != 0

    def test_fails_on_mutable_tag(self, tmp_path: Path) -> None:
        module = _load_module()
        action = tmp_path / "action.yml"
        action.write_text(
            "runs:\n  using: docker\n  image: docker://ghcr.io/alexhawat/mergecraft:latest\n",
            encoding="utf-8",
        )
        module.ACTION_YML = action
        assert module.main() != 0

    def test_fails_on_pre_tracing_digest(self, tmp_path: Path) -> None:
        """Pinned pre-#531 digests must not pass the tracing-extra contract."""
        module = _load_module()
        action = tmp_path / "action.yml"
        action.write_text(
            "runs:\n  using: docker\n  image: "
            "docker://ghcr.io/alexhawat/mergecraft@"
            "sha256:955510ad23e1aa23d564475c2220ec0988236838a914a2a7472ea38220cb1f90\n",
            encoding="utf-8",
        )
        module.ACTION_YML = action
        assert module.main() != 0

    def test_passes_on_repo_action_yml(self) -> None:
        module = _load_module()
        assert module.main() == 0
