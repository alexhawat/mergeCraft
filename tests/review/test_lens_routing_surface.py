"""``LENS_ROUTING_STEP4_NOTE`` had no caller anywhere; the routing helpers stay."""

from __future__ import annotations


def test_lens_routing_step4_note_is_gone() -> None:
    """The unused prompt fragment is deleted from the module and the package re-export."""
    import mergecraft.review as review_package
    from mergecraft.review import lens_routing

    assert "LENS_ROUTING_STEP4_NOTE" not in lens_routing.__all__
    assert not hasattr(lens_routing, "LENS_ROUTING_STEP4_NOTE")
    assert "LENS_ROUTING_STEP4_NOTE" not in review_package.__all__
    assert not hasattr(review_package, "LENS_ROUTING_STEP4_NOTE")
    # Surviving surface: the routing helpers still work.
    assert lens_routing.lens_id_from_agent_id("lens-security") == "security"
    assert callable(lens_routing.route_lenses)
    assert callable(lens_routing.route_lenses_complement)
    assert callable(lens_routing.load_routing_registry)
