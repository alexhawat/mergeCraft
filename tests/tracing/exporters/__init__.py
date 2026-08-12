"""RED contracts for remote tracing exporters (Batch D, W7).

Mirrors the Batch A layout under :mod:`tests.tracing` — the conftest supplies
shared fixtures, the per-contract test files cover one logical concern each.
Every cross-wave marker is non-strict (``strict=False``) so the suite stays
collectible and runnable while W8 ships the implementation.
"""
