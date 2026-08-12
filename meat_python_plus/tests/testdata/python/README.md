# Golden Python corpus (W10)

Upstream fixtures copied from [boldsoftware/meat](https://github.com/boldsoftware/meat) @
`f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3` (`meat/testdata/python/*`) during **Wave W10**.

## Files

| Base | Files |
|------|-------|
| `django-526b1b414d8e` | `.diff`, `.plan.json`, `.golden.diff` |
| `flask-c17f37939073` | `.diff`, `.plan.json`, `.golden.diff` |
| `pytest-b4e846616cbb` | `.diff`, `.plan.json`, `.golden.diff` |

Attribution: see `NOTICE` and `LICENSE.upstream` (Apache License 2.0).
`README.upstream.md` is the upstream corpus README at the same pin (reference only).

Offline suite: `tests/test_python_golden.py` applies each `*.plan.json` via
`compile_edit_plan` and asserts equality with `*.golden.diff` (no live LLM).

## Refresh from upstream pin

See `meat_python_plus/README.md` §Refreshing golden fixtures. Shortcut from repo root:

```bash
PIN=f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3
DEST=meat_python_plus/tests/testdata/python
for base in django-526b1b414d8e flask-c17f37939073 pytest-b4e846616cbb; do
  for ext in diff plan.json golden.diff; do
    curl -fsSL \
      "https://raw.githubusercontent.com/boldsoftware/meat/${PIN}/meat/testdata/python/${base}.${ext}" \
      -o "${DEST}/${base}.${ext}"
  done
done
curl -fsSL \
  "https://raw.githubusercontent.com/boldsoftware/meat/${PIN}/LICENSE" \
  -o "${DEST}/LICENSE.upstream"
```

Update the pin SHA in this README, `NOTICE`, and the package README when the
wave-plan pin moves.
