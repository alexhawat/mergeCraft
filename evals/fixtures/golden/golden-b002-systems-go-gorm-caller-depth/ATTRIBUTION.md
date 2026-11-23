# Upstream attribution

Case: golden-b002-systems-go-gorm-caller-depth. Human decision: pending.

Source repository: https://github.com/go-gorm/gorm
Introducing PR: https://github.com/go-gorm/gorm/pull/7610 by GitHub user ifooth.
Fix PR: https://github.com/go-gorm/gorm/pull/7717 by GitHub user smf-h.

Code and patches remain the work of the upstream contributors.
License: MIT License; complete unmodified text in LICENSE.upstream.
Pinned license: https://github.com/go-gorm/gorm/blob/2c3d109af3057f0d0ee64104011f12ac7bdab9bc/LICENSE

Source .txt files are verbatim bounded excerpts; their original file paths and line ranges are recorded in evidence.json. task.patch is the introducing PR diff filtered to the identified buggy file. fix.patch is the complete fixing PR diff. Diffs come from GitHub compare API pinned to the recorded full base/head SHAs; source excerpts use the recorded merged commit SHAs. No code was reconstructed.

The introduction routes FileWithLineNum through an additional CallerFrame wrapper while retaining runtime.Callers(3). An external wrapper chain is therefore resolved one frame too early, changing the file:line returned by the established helper. The fix chooses explicit stack skips separately for CallerFrame and FileWithLineNum, and tests the wrapped call chain.

Upstream regression tests were inspected, not executed locally. This is proposed evidence for human review; no human label or decision is asserted.
