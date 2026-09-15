# Releasing Tavern

Tavern releases have one version source and one trigger. The version in
`meson.build` is authoritative; the newest AppStream release entry must match
it. A release tag is created only by the manually dispatched **Prepare Release
Tag** workflow. Merging to `main` never invents or increments a version.

## Release checklist

1. Update the version in `meson.build` and prepend the matching release entry
   in `data/org.tunaos.tavern.metainfo.xml.in`.
2. Run `python3 tools/validate-release.py --version X.Y.Z`, the test suite, and
   the Flatpak build.
3. Merge the release-preparation PR to `main`.
4. Dispatch **Prepare Release Tag** with `X.Y.Z`.
5. Prepare Release Tag explicitly dispatches Release at that tag. A tag push
   made with `GITHUB_TOKEN` alone does not start another workflow.
   Release validates the tag/metadata contract,
   builds all three formats, creates one GitHub release, and publishes SHA-256
   checksums, an SPDX SBOM, and signed GitHub attestations.
6. Verify an artifact with `gh attestation verify ARTIFACT --repo tuna-os/Tavern`
   and compare it with `SHA256SUMS` before updating downstream packaging.

The org tap owns `Casks/tavern.rb`. Tavern changes only its version and two
checksums. The updater needs `TAP_GITHUB_TOKEN` with write access to that tap.
Before a release with new AppImage paths, update the cask structure in the tap.
In particular, the v0.1.9 cask uses `dev.hanthor.Tavern` desktop and icon paths;
a release with `org.tunaos.tavern` paths needs a matching tap change.
The updater preserves these paths; it does not infer a migration.

The recommended Flatpak also follows tested `main` commits through `prod`.
This rolling channel can contain changes beyond the latest numbered release.
Record channel versions and install results in #104 before claiming parity.
Tags without a GitHub Release are historical source markers, not published
releases. Do not delete or repoint them.

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
