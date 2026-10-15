"""Human-readable duration formatting for operator-facing review output."""

from __future__ import annotations


def format_duration(total_seconds: float) -> str:
    """Format a non-negative duration in seconds as ``3m 11s`` / ``1h 2m 3s``."""
    seconds_int = max(0, int(total_seconds))
    minutes, seconds = divmod(seconds_int, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


__all__ = ["format_duration"]
