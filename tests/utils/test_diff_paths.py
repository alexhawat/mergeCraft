"""Every path a diff touches, including the entries that carry no hunk.

``changed_paths_from_diff`` feeds the policy gate, the evidence packet's blast
radius and verifier confinement, so a path the diff *touches* must appear even
when there is no line to attribute to it:

* a pure rename (``similarity index 100%``) moves a file without adding or
  removing a line, and both the old and the new path were touched — the old one
  because it stopped existing, the new one because it started;
* a binary-only entry and a mode-only entry change a file without a hunk.

The diff texts below are shaped exactly as git renders them (captured from real
``git diff`` output), so the parser is exercised against the format it meets in
a review rather than a hand-simplified one.

These tests are written before the parser reports those entries, so they are red
until the implementation lands.
"""

from __future__ import annotations

from mergecraft.utils.diff_paths import changed_paths_from_diff

# ``git mv .mergecraft/policy/rules.yaml .mergecraft/policy/rules.yaml.bak``
# with no content change: no ``---``/``+++`` lines and no hunk.
_RENAME_DIFF = """\
diff --git a/legacy/old.py b/modern/new.py
similarity index 100%
rename from legacy/old.py
rename to modern/new.py
"""

# A byte change git cannot show as text.
_BINARY_DIFF = """\
diff --git a/assets/logo.bin b/assets/logo.bin
index 8352675..6d5b70e 100644
Binary files a/assets/logo.bin and b/assets/logo.bin differ
"""

# ``chmod 644 scripts/deploy.sh && chmod 755 scripts/deploy.sh``: no content change.
_MODE_DIFF = """\
diff --git a/scripts/deploy.sh b/scripts/deploy.sh
old mode 100644
new mode 100755
"""

# The ordinary shapes: a modification with a hunk and a new file.
_HUNK_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
diff --git a/src/new.py b/src/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1 @@
+y = 3
"""


def test_a_pure_rename_returns_both_paths() -> None:
    """A rename touches the path that disappears and the path that appears."""
    paths = changed_paths_from_diff(_RENAME_DIFF)

    assert paths == ["legacy/old.py", "modern/new.py"]


def test_a_binary_only_entry_returns_its_path() -> None:
    """No hunk, no ``---``/``+++``: the binary entry still names a changed file."""
    paths = changed_paths_from_diff(_BINARY_DIFF)

    assert paths == ["assets/logo.bin"]


def test_a_mode_only_entry_returns_its_path() -> None:
    """A permission bit change is a change to the file it names."""
    paths = changed_paths_from_diff(_MODE_DIFF)

    assert paths == ["scripts/deploy.sh"]


def test_a_hunk_diff_keeps_its_result_sorted_and_deduplicated() -> None:
    """Hunk-bearing edits and additions keep their current answer exactly."""
    paths = changed_paths_from_diff(_HUNK_DIFF)

    assert paths == ["src/app.py", "src/new.py"]
    assert paths == sorted(set(paths))
