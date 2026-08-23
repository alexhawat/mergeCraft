"""Provider stream bookkeeping stamps only the active open pair."""

from __future__ import annotations

from mergecraft.agents.stream_bookkeeping import sync_open_pair_bookkeeping


def test_sync_open_pair_bookkeeping_stamps_only_active_key() -> None:
    bookkeeping = {
        "thread-a": {"tokens_in": 0, "tokens_out": 0},
        "thread-b": {"tokens_in": 0, "tokens_out": 0},
    }
    usage = {"input_tokens": 11, "output_tokens": 3}

    sync_open_pair_bookkeeping(bookkeeping, usage, active_key="thread-b")

    assert bookkeeping["thread-a"] == {"tokens_in": 0, "tokens_out": 0}
    assert bookkeeping["thread-b"] == {"tokens_in": 11, "tokens_out": 3}


def test_sync_open_pair_bookkeeping_defaults_to_sole_open_pair() -> None:
    bookkeeping = {"default": {"tokens_in": 0, "tokens_out": 0}}

    sync_open_pair_bookkeeping(bookkeeping, {"input_tokens": 4, "output_tokens": 1})

    assert bookkeeping["default"] == {"tokens_in": 4, "tokens_out": 1}


def test_sync_open_pair_bookkeeping_defaults_to_last_open_pair() -> None:
    bookkeeping = {
        "thread-a": {"tokens_in": 0, "tokens_out": 0},
        "thread-b": {"tokens_in": 0, "tokens_out": 0},
    }

    sync_open_pair_bookkeeping(bookkeeping, {"input_tokens": 9, "output_tokens": 2})

    assert bookkeeping["thread-a"] == {"tokens_in": 0, "tokens_out": 0}
    assert bookkeeping["thread-b"] == {"tokens_in": 9, "tokens_out": 2}


def test_sync_open_pair_bookkeeping_treats_non_numeric_usage_as_zero() -> None:
    bookkeeping = {"default": {"tokens_in": 0, "tokens_out": 0}}

    sync_open_pair_bookkeeping(
        bookkeeping,
        {"input_tokens": "bad", "output_tokens": None},
    )

    assert bookkeeping["default"] == {"tokens_in": 0, "tokens_out": 0}
