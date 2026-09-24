---
description: Review on a third-party model — pin a gateway, then run the deep engine
agent: build
---

Pin a third-party OpenAI-compatible model on the `opencode` harness, then review
the current change. Requested model: $ARGUMENTS

1. Confirm the endpoint is configured. The pair is
   `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL` and `MERGECRAFT_CUSTOM_PROVIDER_API_KEY`
   (indexed `_1`, `_2`, … for multiple entries). Read
   `docs/authentication.md` and print the exact secret names for the user to set;
   never handle the key yourself.
2. Register the model and select the harness:

   ```bash
   mergecraft model add "<provider>/<model>"
   mergecraft models set '["<provider>/<model>"]'
   ```

   In `.mergecraft/config.yaml`, ensure `harness: opencode` is set so a
   non-first-party slug routes to the OpenCode harness.
3. Review:

   ```bash
   mergecraft review
   ```

If `$ARGUMENTS` is empty, ask which provider/model to use and stop — do not
invent a slug.
