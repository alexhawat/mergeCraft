---
description: Set up mergeCraft AI PR review in the current repository
---

Set up mergeCraft in this repo by following the skill's setup checklist:

1. Verify Python **3.11+**, uv, and an authenticated `gh` CLI. If Python 3.11+
   is unavailable locally, use the Docker Action path only — no local CLI required
   for CI ([`docs/install.md`](../docs/install.md)).
2. Run:

   ```bash
   uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
   mergecraft init
   ```

3. **STOP before authentication.** Ask me to run the interactive
   `mergecraft provider auth <provider> --scope github` step (a configured label or id from `mergecraft provider list`; see
   [`docs/authentication.md`](../docs/authentication.md)). Never invent or commit
   credentials or secrets.
4. Commit only `.mergecraft/config.yaml` and `.github/workflows/mergecraft.yml`
   on a new branch and open a pull request.
