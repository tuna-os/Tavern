# Accessibility regression checklist

Run the automated host and Flatpak-sandbox widget tests first. Then do this release check with keyboard navigation and Orca:

1. Browse, search, filter, reset filters, and press Enter to open the first result.
2. Open details. Confirm that Orca announces name, package type, install state, compatibility, and security advisory state in a useful order.
3. Install, update, remove, and cancel work from Downloads & Tasks. Confirm queued, active, completed, failed, and cancelled states remain distinct.
4. Open a screenshot. Verify that Orca announces the caption. Verify `+`, `-`, and `0` zoom. Confirm that Escape leaves fullscreen before the window closes, and every icon button has a name.
5. Repeat with system animations disabled and confirm the screenshot viewer does not fade in.
6. Repeat in high-contrast mode and confirm keyboard focus and warning/status icons remain visible.

Automated smoke tests in CI check labels on packages, keyboard search activation, filter reset, task cancellation states, screenshot keyboard zoom, and the Flatpak widget path. A manual Orca pass remains required before a release because automated trees do not judge the quality of announcements.
