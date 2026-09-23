# Judge calibration inputs

This directory is reserved for frozen, independently human-labelled paired
judge cases, their explicit acceptance protocol, and candidate seals created
after calibration and before held-out scoring. None are committed yet.

The nine metadata-only rows prepared by plan 011 are not calibration cases:
they have no candidate finding, saved judge verdict, recovered evidence, or
human reference. Do not convert those rows into this format until the named
human has reviewed immutable evidence.

Test-only synthetic pairs live under `tests/` and do not support a product or
calibration claim.
