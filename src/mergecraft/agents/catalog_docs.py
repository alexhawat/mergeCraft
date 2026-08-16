"""Agent registry validation gate — mirror of ``analyzers/catalog_docs`` (AP1)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.agents.registry import RegistryValidationError, load_registry
from mergecraft.config.settings import default_settings, load_repo_settings


def validate_agent_registry(*, repo_root: Path | None = None) -> None:
    """Validate bundled defaults and every known prompt/model reference."""
    root = repo_root or Path(__file__).resolve().parents[3]
    settings = (
        load_repo_settings(root=root)
        if (root / ".mergecraft" / "config.yaml").is_file()
        else default_settings()
    )
    registry = load_registry(settings=settings, repo_root=root)
    try:
        registry.validate()
    except RegistryValidationError as exc:
        msg = f"agent registry validation failed: {exc}"
        raise SystemExit(msg) from exc

    # Defaults-only pass — every core role must resolve.
    for role in ("orchestrator", "reviewer", "verifier", "judge", "classifier"):
        binding = registry.resolve_role(role)
        if not binding.model_chain:
            msg = f"default binding for {role!r} has empty model_chain"
            raise SystemExit(msg)


def main() -> None:
    validate_agent_registry()


if __name__ == "__main__":
    main()
