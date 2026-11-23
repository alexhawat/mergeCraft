# Upstream attribution

Case: golden-b002-systems-java-spring-composite-set-remove. Human decision: pending.

Source repository: https://github.com/spring-projects/spring-framework
Introducing PR: https://github.com/spring-projects/spring-framework/pull/37332 by GitHub user quaff.
Fix PR: https://github.com/spring-projects/spring-framework/pull/37394 by GitHub user lejuho.

Code and patches remain the work of the upstream contributors.
License: Apache License 2.0; complete unmodified text in LICENSE.upstream.
Pinned license: https://github.com/spring-projects/spring-framework/blob/f5a71230440381427d7d652e94a44a8658357025/LICENSE.txt

The complete upstream Apache NOTICE template is preserved in NOTICE.upstream.

Source .txt files are verbatim bounded excerpts; their original file paths and line ranges are recorded in evidence.json. task.patch is the complete introducing PR diff. fix.patch is the complete fixing PR diff. Diffs come from GitHub compare API pinned to the recorded full base/head SHAs; source excerpts use the recorded merged commit SHAs. No code was reconstructed.

The introduced short-circuit OR skips removing the element from the second collection after the first removal succeeds. CompositeSet inherits this behavior and backs CompositeMap.keySet(); deleting an overlapping key therefore reveals the previously hidden second-map entry instead of removing the mapping. The fix overrides set removal to evaluate removals against both sets.

Upstream regression tests were inspected, not executed locally. This is proposed evidence for human review; no human label or decision is asserted.
