"""Validate the tracing sink selector (``tracing-to`` / ``MERGECRAFT_TRACING_TO``).

The sink shorthand is the one control-carrying tracing value whose typo used to
escape classification: it raised a bare ``ValueError`` during run setup, which the
Action reported as ``infra_error`` (the outcome of an unclassified crash) and the
CLI reported with a traceback. :class:`TracingSinkError` subclasses
:class:`~mergecraft.config.env.EnvSettingsError`, so both entrypoints that already
map a malformed tracing value to a configuration failure — the Action's startup
``try`` and the CLI ``main()`` — map this one the same way.

With tracing **off** the value changes nothing about the run, so it stays ignored;
the operator is told by a warning that names the variable and the value instead.

Module: mergecraft.config.tracing_sink
Depends: loguru, mergecraft.config.env

Exports:
    Classes:
        TracingSinkError — an unknown sink shorthand that must fail configuration.
    Functions:
        check_tracing_sink — raise when tracing is on, warn when it is off.
    Constants:
        TRACING_SINK_SHORTHANDS — the closed shorthand vocabulary.
"""

from __future__ import annotations

from typing import Final

from loguru import logger

from mergecraft.config.env import EnvSettingsError

__all__ = ["TRACING_SINK_SHORTHANDS", "TracingSinkError", "check_tracing_sink"]

TRACING_SINK_SHORTHANDS: Final[tuple[str, ...]] = ("local_files", "logfire", "otel")


class TracingSinkError(EnvSettingsError):
    """An unknown tracing sink shorthand, named with the variable that carried it.

    Unlike the secret-bearing values :class:`EnvSettingsError` guards, a sink name
    is not sensitive, and naming it is what lets the operator see the typo.
    """

    def __init__(self, variable: str, value: str) -> None:
        # Bypass ``EnvSettingsError.__init__``, which discards the value on purpose.
        ValueError.__init__(
            self,
            f"unknown tracing-to sink {value!r} in {variable} "
            f"(expected one of {', '.join(TRACING_SINK_SHORTHANDS)})",
        )
        self.variable = variable
        self.value = value


def check_tracing_sink(
    variable: str,
    value: str | None,
    *,
    enabled: bool,
    warn: bool = True,
) -> None:
    """Reject an unknown sink shorthand when tracing is on; warn when it is off.

    An unset or empty value is "no opinion" and always passes. ``warn=False`` lets a
    hot path (one that resolves tracing many times per run) validate without
    repeating the off-case warning.

    Raises:
        TracingSinkError: ``value`` is not a known shorthand and ``enabled`` is true.
    """
    if value is None or not value.strip() or value in TRACING_SINK_SHORTHANDS:
        return
    if enabled:
        raise TracingSinkError(variable, value)
    if warn:
        logger.warning(
            "tracing is off; ignoring unknown tracing-to sink {!r} in {} (expected one of {})",
            value,
            variable,
            ", ".join(TRACING_SINK_SHORTHANDS),
        )
