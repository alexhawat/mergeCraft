"""yes.op retry primitive tests."""

from __future__ import annotations

import pytest

from mergecraft.yes import OpOptions, op


@pytest.mark.asyncio
async def test_op_retries_then_succeeds() -> None:
    calls = {"n": 0}

    async def flaky(_input: object = None) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            msg = "transient"
            raise RuntimeError(msg)
        return "ok"

    wrapped = op(flaky, OpOptions(retries=[1, 1], name="flaky"))
    assert await wrapped(None) == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_op_bail_skips_retries() -> None:
    calls = {"n": 0}

    async def always_fail(_input: object = None) -> str:
        calls["n"] += 1
        msg = "fatal"
        raise RuntimeError(msg)

    wrapped = op(
        always_fail,
        OpOptions(retries=[1, 1], bail=lambda e: "fatal" in str(e)),
    )
    with pytest.raises(RuntimeError, match="fatal"):
        await wrapped(None)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_op_exhausts_retries() -> None:
    async def always_fail(_input: object = None) -> str:
        msg = "nope"
        raise RuntimeError(msg)

    wrapped = op(always_fail, {"retries": [1]})
    with pytest.raises(RuntimeError, match="nope"):
        await wrapped(None)
