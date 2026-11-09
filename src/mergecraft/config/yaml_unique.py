"""Strict YAML loading for config files: duplicate mapping keys are an error (#1250)."""

from __future__ import annotations

from typing import Any

import yaml
from yaml.constructor import ConstructorError


class ConfigParseError(ValueError):
    """A config file exists but cannot be parsed; runs map this to ``configuration_error``."""


class DuplicateKeyError(yaml.YAMLError):
    """A mapping repeats a key; ``str()`` carries the key and line, never values."""

    def __init__(self, key: object, line: int) -> None:
        super().__init__(f"duplicate key {key!r} at line {line}")


class UniqueKeySafeLoader(yaml.SafeLoader):
    """``SafeLoader`` that rejects duplicate keys in any mapping, at any depth.

    PyYAML keeps the last value for a repeated key, so a second ``shell:`` line
    could silently override the first. The error names the key and line but
    never the values, which may carry credentials.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            try:
                key = self.construct_object(key_node, deep=True)
                hash(key)
            except (TypeError, ConstructorError):
                continue  # let the base class report unhashable / bad keys
            if key in seen:
                raise DuplicateKeyError(key, key_node.start_mark.line + 1)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def safe_load_unique(text: str) -> Any:
    """Parse *text* with :class:`UniqueKeySafeLoader` (YAML 1.1 safe subset)."""
    return yaml.load(text, Loader=UniqueKeySafeLoader)


__all__ = ["ConfigParseError", "DuplicateKeyError", "UniqueKeySafeLoader", "safe_load_unique"]
