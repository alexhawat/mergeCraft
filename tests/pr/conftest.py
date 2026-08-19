"""Shared fixtures for DG8 PR utility RED tests."""

from __future__ import annotations

import pytest

_SAMPLE_DIFF = """diff --git a/src/auth/login.py b/src/auth/login.py
index 1111111..2222222 100644
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -10,6 +10,9 @@ def login(user, password):
     if not user:
         return None
+    # TODO: remove this guard before launch
+    if password == "admin":
+        return user
     return _verify(user, password)
"""

_SAMPLE_PR_METADATA: dict[str, object] = {
    "number": 42,
    "title": "Add admin shortcut login",
    "body": "Temporary admin login for staging.",
    "labels": ["enhancement"],
    "author_association": "MEMBER",
}


@pytest.fixture
def sample_diff() -> str:
    return _SAMPLE_DIFF


@pytest.fixture
def sample_pr_metadata() -> dict[str, object]:
    return dict(_SAMPLE_PR_METADATA)
