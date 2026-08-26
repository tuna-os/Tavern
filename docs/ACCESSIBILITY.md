# Accessibility regression checklist

Run the automated host and Flatpak-sandbox widget tests first, then perform this release check with keyboard navigation and Orca:

1. Browse, search, filter, reset filters, and press Enter to open the first result.
2. Open details and confirm name, package type, install state, compatibility, and security advisory state are announced once and in a useful order.
3. Install, update, remove, and cancel work from Downloads & Tasks. Confirm pending, running, completed, failed, and cancelled states remain distinguishable.
4. Open a screenshot. Verify the caption is announced; `+`, `-`, and `0` zoom; Escape leaves fullscreen before closing; and every icon button has a name.
5. Repeat with system animations disabled and confirm the screenshot viewer does not fade in.
6. Repeat in high-contrast mode and confirm keyboard focus and warning/status icons remain visible.

The CI smoke coverage checks accessible package labels, search keyboard activation, filter state/reset, task cancellation states, screenshot keyboard zoom, and the Flatpak widget path. A manual Orca pass remains required before a release because automated accessibility trees cannot judge announcement quality.
