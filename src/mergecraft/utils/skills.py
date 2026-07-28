"""Install bundled skills into agent skill directories."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

BUNDLED_SKILL_NAMES: tuple[str, ...] = ("git-archaeology",)
SKILL_TARGET_DIRS: tuple[str, ...] = (".opencode/skills", ".claude/skills", ".agents/skills")


def _resolve_skill_path(name: str) -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "skills" / name / "SKILL.md",
        here / "skills" / name / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    msg = f"bundled skill not found: {name} (looked in {', '.join(str(c) for c in candidates)})"
    raise FileNotFoundError(msg)


def install_bundled_skills(*, home: str) -> None:
    """Write bundled skills into agent auto-scan dirs under ``home``."""
    home_path = Path(home)
    for name in BUNDLED_SKILL_NAMES:
        content = _resolve_skill_path(name).read_text(encoding="utf-8")
        for target_dir in SKILL_TARGET_DIRS:
            skill_dir = home_path / target_dir / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    logger.success("installed bundled skills: {}", ", ".join(BUNDLED_SKILL_NAMES))


__all__ = [
    "BUNDLED_SKILL_NAMES",
    "SKILL_TARGET_DIRS",
    "install_bundled_skills",
]
