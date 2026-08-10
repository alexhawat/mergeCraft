"""Batch C RED suite — stream-json migration for agent drivers.

The W5 RED suite pins the contracts that W6 must satisfy to migrate drivers
from ``capture_output=True`` JSON-blob parsing to incremental ``stream-json``
consumption. The suite covers:

- per-``tool.call`` and per-``llm.call`` spans from a recorded stream (W5.1, W5.2);
- malformed-event tolerance (W5.6);
- equivalence of ``AgentResult`` before and after the migration (W5.7);
- graceful degradation for non-streaming drivers (W5.3, D12);
- regression pins for ``utils/activity.py`` idle detection (W5.4, D13);
- regression pin for PR #16's stderr-at-warning failure diagnosis (W5.5, D13).

The tests use **only** ``tests`` for assertions — never touch ``src/mergecraft/``
beyond reading the existing public API. The recording fixtures (a Claude stream
session, a codex ``exec --json`` session, a malformed-stream session) live in
this directory as Python fixtures so they remain readable and diff-friendly.
"""
