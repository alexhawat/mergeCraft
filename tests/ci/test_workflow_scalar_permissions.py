"""Scalar workflow permissions (read-all / write-all) expand before lint."""

from __future__ import annotations

from scripts.workflow_yaml import missing_permissions, permission_dict


def test_permission_dict_expands_read_all() -> None:
    assert permission_dict("read-all") == {"__all_read__": "read"}


def test_permission_dict_expands_write_all() -> None:
    assert permission_dict("write-all") == {"__all_write__": "write"}


def test_read_all_satisfies_contents_read() -> None:
    caller = permission_dict("read-all")
    callee = {"contents": "read"}
    assert missing_permissions(caller, callee) == {}


def test_write_all_satisfies_contents_write() -> None:
    caller = permission_dict("write-all")
    callee = {"contents": "write", "packages": "read"}
    assert missing_permissions(caller, callee) == {}
