# Upstream attribution

Case: golden-b002-systems-rust-tokio-timer-runtime. Human decision: pending.

Source repository: https://github.com/tokio-rs/tokio
Introducing PR: https://github.com/tokio-rs/tokio/pull/8132 by GitHub user vilgotf.
Fix PR: https://github.com/tokio-rs/tokio/pull/8169 by GitHub user ADD-SP.

Code and patches remain the work of the upstream contributors.
License: MIT License; complete unmodified text in LICENSE.upstream.
Pinned license: https://github.com/tokio-rs/tokio/blob/923e72345c77aef4d11875d874ba67421b0412d3/LICENSE

Source .txt files are verbatim bounded excerpts; their original file paths and line ranges are recorded in evidence.json. task.patch is the introducing PR diff filtered to the identified buggy file. fix.patch is the complete fixing PR diff. Diffs come from GitHub compare API pinned to the recorded full base/head SHAs; source excerpts use the recorded merged commit SHAs. No code was reconstructed.

Timer::new computes its deadline using the original runtime handle, then unconditionally pushes the entry onto the current worker runtime registration queue. Resetting a sleep from another runtime can migrate its timer or panic in a current-thread runtime. The introducing patch removed the runtime identity guard; the fix restores the guard and falls back to registration through the original runtime handle.

Upstream regression tests were inspected, not executed locally. This is proposed evidence for human review; no human label or decision is asserted.
