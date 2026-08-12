"""Shared diff fixtures ported from boldsoftware/meat @ f39f41dfe7b5."""

from __future__ import annotations

# Canonical cross-file move (Go surfaceFixtureDiff / exactMoveDiff).
EXACT_MOVE_DIFF = (
    "diff --git a/old.txt b/old.txt\n"
    "--- a/old.txt\n"
    "+++ b/old.txt\n"
    "@@ -1,5 +1,2 @@\n"
    " context\n"
    "-    alpha := prepare(source)\n"
    "-    beta := transform(alpha)\n"
    "-    publish(beta)\n"
    "-    recordSuccess(beta)\n"
    "+old_location_gone = true\n"
    "diff --git a/new.txt b/new.txt\n"
    "--- a/new.txt\n"
    "+++ b/new.txt\n"
    "@@ -1 +1,6 @@\n"
    " context\n"
    "+        alpha := prepare(source)\n"
    "+        beta := transform(alpha)\n"
    "+        publish(beta)\n"
    "+        recordSuccess(beta)\n"
    "+new_location_ready = true\n"
)

EXACT_MOVE_REMOVED = (6, 9)
EXACT_MOVE_ADDED = (16, 19)

SURFACE_FIXTURE_NO_MOVE_DIFF = (
    "diff --git a/a.txt b/a.txt\n"
    "--- a/a.txt\n"
    "+++ b/a.txt\n"
    "@@ -1 +1 @@\n"
    "-old_value = 1\n"
    "+new_value = 2\n"
)

# Go RubricHash pin at upstream f39f41dfe7b5 (full promptSurface hash).
GO_PINNED_RUBRIC_HASH = "441f5e6e28ad3add"

GO_DEFAULT_OPENAI_MODEL = "gpt-5.6-sol"
GO_DEFAULT_REASONING_EFFORT = "medium"
GO_MAX_OPENAI_OUTPUT_TOKENS = 32768

GOLDEN_PYTHON_BASES = (
    "django-526b1b414d8e",
    "flask-c17f37939073",
    "pytest-b4e846616cbb",
)
