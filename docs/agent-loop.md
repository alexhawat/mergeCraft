# Agent loop

Reference workflow for an external coding agent that **changes** code, asks
mergeCraft to **review**, **consumes findings**, **decides** what to change
next, and reviews the new **diff**. This is not a Fix/write loop — mergeCraft
stays review-only.

Do not put this workflow under `skills/` (harness packages ship later via the
README v2 program). The machine surface is `mergecraft review --agent`.

## The five steps

1. **Change** — the external agent edits the working tree (or writes a patch).
2. **Review** — run mergeCraft against that change:
   ```bash
   mergecraft review --agent
   ```
   JSONL events on stdout: `run_started` · `phase` · `finding` · `verdict` ·
   `run_finished`. Each event stamps `protocol_version` (`1`). CLI JSON
   envelopes keep `schema_version` (`1.0.0`); both fields survive and alias
   each other.
3. **Consume findings** — parse each `finding` line as it arrives (before
   `verdict`). Human text, if any, is on stderr; do not redirect stdout away
   from the JSONL stream.
4. **Decide** — the agent chooses the next edit from the findings. mergeCraft
   does not apply fixes, commit, or push.
5. **Review the new diff** — run `mergecraft review --agent` again on the
   updated change. Repeat until the `verdict` / exit code is acceptable.

## Exit codes

Branch on the process exit, not on stderr prose. Full table:
[`docs/EXIT-CODES.md`](EXIT-CODES.md).

Named exits the loop should handle: `0` (pass), `10` (findings), `11`
(blocked), `12` (failed), `20` (inconclusive), `30` (configuration), `40`
(infra), `50` (timeout), `2` (usage).

See also: [`docs/cli.md`](cli.md) (`review --agent`),
[`docs/workflows.md`](workflows.md) (local review examples).
