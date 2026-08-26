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
5. The tag-triggered Release workflow validates the tag/metadata contract,
   builds all three formats, creates one GitHub release, and publishes SHA-256
   checksums, an SPDX SBOM, and signed GitHub attestations.
6. Verify an artifact with `gh attestation verify ARTIFACT --repo tuna-os/Tavern`
   and compare it with `SHA256SUMS` before updating downstream packaging.

Build tools and Python wheels in the release path must use immutable tags or
commits plus a recorded SHA-256. Do not restore `continuous`, `master`, or an
unversioned network `pip install` to a release workflow or Flatpak manifest.
