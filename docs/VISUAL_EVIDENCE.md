# Visual evidence receipts

Screenshots only count when they say which artifact and scenario they show.
`tools/visual_evidence.py` is the acceptance oracle for that (#315).

## Lanes

| Lane | What is photographed | Source binding |
|---|---|---|
| `published-artifact` | The published `org.tunaos.tavern` Flatpak from the tuna-os remote | always `unknown`; never inferred from the checked-out PR |
| `candidate-build` | A bundle built from the checked-out commit and installed from that bundle | `bundle-built-from-commit`, with bundle SHA-256 and commit |

A passing published screenshot never qualifies a candidate, and the lanes
report separately.

## Scenarios

- `no-homebrew`: app reports `brew_available=false`, the missing-Homebrew
  banner is revealed, and the no-Homebrew message is present.
- `populated-fixture`: deterministic fixture catalog loaded. This is fixture
  state, not a real supported host with Homebrew.

## Verification

```bash
python3 tools/visual_evidence.py verify --receipt out/receipt.json \
  --out-dir out --lane candidate-build --scenario no-homebrew \
  --run-id "$GITHUB_RUN_ID" --run-attempt "$GITHUB_RUN_ATTEMPT" \
  --source-sha "$GITHUB_SHA" --bundle-sha256 "$BUNDLE_SHA256"
```

Exit 1 on any of: wrong lane/scenario/run, substituted published package,
wrong app/runtime/source/bundle digest, PNG not matching the receipt hash,
extra images in the output directory, unrelated window, loading/error screen,
missing app-state readback or expected message, missing frames, recorded
failures, or missing cleanup result.

## Freshness and limits

Receipts are allowlisted JSON (schema 1): lane, scenario, run id/attempt,
artifact, source, environment, state, frame hashes, failures, cleanup. No
environment dump, secrets or user data. Output directories must be fresh per
run; committed `docs/screenshots/` images are never accepted as evidence and
are never updated from CI. Not covered: a real host with Homebrew, other
desktops, other architectures.
