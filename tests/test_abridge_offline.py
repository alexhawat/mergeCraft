"""Offline abridge test with a fake Model that submits a remove plan."""

from meat_python_plus.abridge import Request, abridge
from meat_python_plus.model import Block, Message, Response, Tool

DIFF = """diff --git a/demo.py b/demo.py
--- a/demo.py
+++ b/demo.py
@@ -1,3 +1,3 @@
 keep_me = True
-noise_one = 1
-noise_two = 2
+noise_one = 10
+noise_two = 20
"""


class KeepOneChange:
    """Submit a plan that keeps one behavioral change line."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> Response:
        self.calls += 1
        assert "reading diff" in system.lower() or "code-reading" in system.lower()
        assert any(t.name == "submit" for t in tools)
        # 1 header, 2 ---, 3 +++, 4 @@, 5 keep_me, 6-7 old, 8-9 new
        return Response(
            content=[
                Block(
                    type="tool_use",
                    id="call_1",
                    tool_name="submit",
                    tool_input={
                        "remove": [
                            {"start_line": 6, "end_line": 7},
                            {"start_line": 9, "end_line": 9},
                        ],
                        "replace": [],
                        "fold": [],
                        "summary": "Shows the noise_one update.",
                    },
                )
            ],
            input_tokens=3,
            output_tokens=2,
        )


def test_abridge_offline_remove_plan():
    model = KeepOneChange()
    res = abridge(model, Request(unified_diff=DIFF, repo_root=""))
    assert model.calls == 1
    assert "Shows the noise_one update" in res.summary
    assert "+noise_one = 10" in res.smart_diff
    assert "-noise_one" not in res.smart_diff
    assert "noise_two" not in res.smart_diff
    assert "keep_me" in res.smart_diff
    assert res.input_tokens == 3


def test_abridge_empty_diff():
    class Boom:
        def generate(self, *a, **k):  # type: ignore[no-untyped-def]
            raise AssertionError("should not call model")

    res = abridge(Boom(), Request(unified_diff="   "))  # type: ignore[arg-type]
    assert res.summary == "No changes."
