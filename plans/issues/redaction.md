## Verified defect
Audited main `be9993367386b03f982c795ceb1d80e4a0bfcf1d` on 2026-09-22. No real credentials were used in verification.

[`record_tool_call`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/evidence/trajectory.py#L509) redacts the command at line 520 but separately passes raw arguments to `_paths_in` at line 521. [The extractor](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/evidence/trajectory.py#L375) accepts the entire command string as a path whenever it contains a slash or dot. A synthetic credential inside `grep <synthetic-token> src/app.py` is consequently removed from `command` but retained in `paths` and `files_read`.

[`run_packet.py`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/evidence/run_packet.py#L397) embeds that trajectory; [the packet writer](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/evidence/emit.py#L36) serializes it verbatim. This bypass reaches the evidence artifact even when command redaction works.

## Reproduction
Use only a fabricated sentinel (for example construct `'ghp_' + '0123456789abcdefghijklmnopqrstuvwxyzABCD'`) and call `record_tool_call` with shell arguments `{'command': f'grep {sentinel} src/app.py'}`, then `build_trajectory_record`.

Observed membership checks:
```
synthetic_retained_in_command: false
synthetic_retained_in_paths: true
synthetic_retained_in_serialized_trajectory: true
```

## Acceptance
- Extract paths from documented tool fields/operands, never arbitrary argument values or whole command bodies.
- Apply the existing secret-redaction policy before any extracted string is stored or serialized; sanitize external/native trajectory input too.
- Regression tests verify absence of synthetic sentinels throughout ToolCallRecord, files_read, run-health evidence and the serialized packet, while valid repo paths remain useful.
- Bound stored path lengths and retain authoritative run-diff-only files_modified behavior.
- No real keys in tests, logs or issue artifacts.

Related: #796 fixed modified-path inflation but did not close this separate redaction route. Priority P1; effort S/M; fix risk medium. Implementation plan: `plans/001-trajectory-redaction.md`.
