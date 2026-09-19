## Withdrawn review findings (known non-issues)

<!-- mergecraft-finding:v1:aaaaaaaaaaaaaaaaaaaaaaaa -->

`wrap_agent_command` dropping uid without redirecting `$HOME` was raised and then withdrawn: the image already sets `HOME` to an agent-owned directory before the drop, so the finding is a known non-issue on this path.
