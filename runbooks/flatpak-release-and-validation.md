# Flatpak Release & Validation Runbook

## Overview
This runbook describes the procedure for validating and publishing Flatpak releases for Tavern (`org.tunaos.tavern`).

## Preflight Verification
1. Ensure `org.tunaos.tavern.json` manifest references correct dependency tags and commit hashes.
2. Validate AppStream metainfo with `appstreamcli validate data/org.tunaos.tavern.metainfo.xml.in` (if appstreamcli is present).
3. Test local Flatpak build using `just build` or `flatpak-builder --force-clean build-dir org.tunaos.tavern.json`.

## Release Steps
1. Verify version numbers in `meson.build` and AppStream metainfo.
2. Run test suite: `pytest` / `just test`.
3. Verify AppStream release notes entry present in metainfo.
4. Execute release packaging instructions per `docs/RELEASING.md`.

## Rollback Procedure
If a published Flatpak release contains critical regressions:
1. Revert the release commit on `main`.
2. Trigger the release workflow for the previous stable commit tag.
3. Post an incident report using the standard incident template `.github/ISSUE_TEMPLATE/incident_report.md`.
