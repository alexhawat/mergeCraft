"""Finding carryover — what a review raised that a merge would otherwise bury.

A merged pull request keeps its inline review comments forever, but nobody
re-opens a merged PR. Findings mergeCraft raised and the author neither fixed
nor rebutted are therefore lost to attention, not to storage. This package
turns those threads back into work: it reads them, decides which ones survive,
and renders each into an issue keyed by the finding fingerprint the reviewer
already stamps.
"""

from __future__ import annotations
