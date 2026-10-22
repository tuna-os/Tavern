# Releasing Tavern

Tavern releases have one version source and one trigger.
The version in `meson.build` is authoritative; the newest release entry in AppStream must match it.
After the `Tests` workflow passes on `main`, **Prepare Release Tag** reads that version, validates it, tags the tested commit, and dispatches the release workflow.
A merge to `main` never invents or increments a version.

## Release checklist

1. Update the version in `meson.build` and prepend the matching release entry
   in `data/org.tunaos.tavern.metainfo.xml.in`.
2. Run `python3 tools/validate-release.py --version X.Y.Z`, the test suite, and
   the Flatpak build.
3. Merge the release-preparation PR to `main` and wait for `Tests` to pass.
4. Prepare Release Tag runs automatically after that successful test workflow.
5. The **Prepare Release Tag** workflow dispatches **Release** at that tag.
   A tag push made with `GITHUB_TOKEN` alone does not start another workflow.
   Release validates the tag/metadata contract and builds all three formats.
   It creates one GitHub release, and publishes SHA-256 checksums, an SPDX SBOM, and signed attestations.
6. Verify an artifact with `gh attestation verify ARTIFACT --repo tuna-os/Tavern`.
   Compare it with `SHA256SUMS` before you update downstream packages.

The org tap owns `Casks/tavern.rb`. Tavern changes only its version and two
checksums. The updater needs `TAP_GITHUB_TOKEN` with write access to that tap.
Before a release with new AppImage paths, update the cask structure in the tap.
In particular, the v0.1.9 cask uses `dev.hanthor.Tavern` desktop and icon paths;
a release with `org.tunaos.tavern` paths needs a matching tap change.
The updater preserves these paths; it does not infer a migration.

The recommended Flatpak also follows tested `main` commits through `prod`.
This channel can contain changes beyond the latest numbered release.
Record channel versions and install results in #104 before you claim parity.
Tags without a GitHub Release are historical source markers, not published
releases. Do not delete or repoint them.

## Release parity gate

The `Verify release parity` job runs after the Release workflow publishes the
release. A tag is a stable release only when each channel has it:

- the GitHub Release, with the AppImage, Flatpak bundle, and macOS assets
- the Flatpak OCI image on ghcr.io
- the Homebrew cask in tuna-os/homebrew-tap

The job examines the GitHub Release and its assets at once. Other workflows
publish the cask and the OCI image later. Thus the job runs
`tools/check-release-parity.py` again and again for a maximum of 20 minutes.
If a channel does not have the tag after that time, the job fails. If the job
cannot read a channel (token scope, registry down), it shows a warning and
does not fail.

Run the gate locally against any tag:

```bash
python3 tools/check-release-parity.py --tag v0.1.64
```

## Recover a failed promotion

Inspect `git log main..origin/prod` first. Merge production-only fixes into a
branch from `main`, test it, then merge the PR with a merge commit. A squash
would lose the ancestry needed for `git merge --ff-only` on `prod`.
Keep the fast-forward guard. Never force-push `prod` to bypass it.

For an app regression, revert the faulty change through a tested PR on `main`.
Promotion then publishes the repaired commit. For a numbered release, use a
new patch version; do not overwrite old tags or release assets.
Use the [diagnostic guide](DIAGNOSTICS.md) to report a failure.

Build tools and Python wheels in the release path must use immutable tags or
commits plus a recorded SHA-256. Do not restore `continuous`, `master`, or an
unversioned network `pip install` to a release workflow or Flatpak manifest.
