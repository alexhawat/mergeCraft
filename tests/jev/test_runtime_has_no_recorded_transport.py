"""Recorded test transports do not ship in the runtime Jev package.

``RecordedTransport`` and ``FlakyRecordedTransport`` replay fixtures and belong
with the test suite. The runtime keeps the ``JevTransport`` protocol and the
live TypeSafe transport.
"""

from __future__ import annotations

import mergecraft.jev.client as client_module
import tests.jev.support as jev_support


def test_runtime_client_has_no_recorded_transports() -> None:
    """The runtime module exports neither recorded transport; the live pair stays."""
    assert not hasattr(client_module, "RecordedTransport")
    assert not hasattr(client_module, "FlakyRecordedTransport")
    assert "RecordedTransport" not in client_module.__all__
    assert "FlakyRecordedTransport" not in client_module.__all__
    # Surviving surface: the runtime transports stay in the package.
    assert hasattr(client_module, "JevTransport")
    assert hasattr(client_module, "LiveTypeSafeTransport")
    assert "JevTransport" in client_module.__all__
    assert "LiveTypeSafeTransport" in client_module.__all__


def test_tests_support_provides_both_recorded_transports() -> None:
    """The test support module owns both recorded transports."""
    recorded = getattr(jev_support, "RecordedTransport", None)
    flaky = getattr(jev_support, "FlakyRecordedTransport", None)
    assert isinstance(recorded, type)
    assert isinstance(flaky, type)
    # Surviving surface: the recorded fixtures the transports replay stay pinned.
    assert jev_support.TRANSPORT_DIR.is_dir()
