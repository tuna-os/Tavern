# Visual evidence receipts

Screenshots only count when they say which artifact and scenario they show.
`tools/visual_evidence.py` is the acceptance oracle for that (#315).

## Lanes

| Lane | What is photographed | Source binding |
|---|---|---|
| `published-artifact` | The published `org.tunaos.tavern` Flatpak from the tuna-os remote | always `unknown`; never inferred from the checked-out PR |
| `candidate-build` | A bundle built from the checked-out commit and installed from that bundle | `bundle-built-from-commit`, with bundle SHA-256 and commit |

A good published screenshot never qualifies a candidate. Each lane reports
its own result.

## Scenarios

- `no-homebrew`: app reports `brew_available=false`, the missing-Homebrew
  banner shows, and the no-Homebrew message is present.
- `populated-fixture`: the app loads a fixed fixture catalog. This is fixture
  state, not a real supported host with Homebrew.

## Verification

```bash
python3 tools/visual_evidence.py verify --receipt out/receipt.json \
  --out-dir out --lane candidate-build --scenario no-homebrew \
  --run-id "$GITHUB_RUN_ID" --run-attempt "$GITHUB_RUN_ATTEMPT" \
  --runtime "$EXPECTED_RUNTIME" \
  --source-sha "$GITHUB_SHA" --bundle-sha256 "$BUNDLE_SHA256"
```

`--runtime` is required for both lanes. `--source-sha` and `--bundle-sha256`
are required for `candidate-build`. The command also exits 1 if any of them
is missing or empty.

The command exits 1 if any of these is true:

- The lane, scenario or run is wrong.
- A published package replaces the expected one.
- The app, runtime, source or bundle digest is wrong.
- A PNG does not match the receipt hash.
- The output directory holds extra images.
- The window is not the app window.
- The screen shows a load or error state.
- The app-state readback or expected message is missing.
- Frames are missing.
- The receipt records failures.
- The cleanup result is missing.

## Freshness and limits

A receipt is JSON (schema 1) with a fixed list of fields. The fields are lane,
scenario, run id, run try number, artifact, source, environment, state, frame
hashes, failures and cleanup. It holds no environment dump, secrets or user data.

Use a fresh output directory for each run. The verifier never accepts
committed `docs/screenshots/` images as evidence, and CI never updates them. Not covered: a real host with Homebrew, other
desktops, other architectures.
