# Accessibility regression checklist

Run the automated host and Flatpak-sandbox widget tests first, then do this release check with keyboard navigation and Orca:

1. Browse, search, filter, reset filters, and press Enter to open the first result.
2. Open details. Confirm that Orca announces each item once, in order: name, package type, install state, compatibility, and security advisory state.
3. Install, update, remove, and cancel work from Downloads & Tasks. Confirm that you can tell apart the queued, active, completed, failed, and cancelled states.
4. Open a screenshot. Verify that Orca announces the caption. Verify that `+`, `-`, and `0` zoom, and that Escape leaves fullscreen before it closes the viewer. Verify that every icon button has a name.
5. Repeat with system animations disabled and confirm the screenshot viewer does not fade in.
6. Repeat in high-contrast mode and confirm keyboard focus and warning/status icons remain visible.

The smoke tests in CI examine the accessible labels of packages and the keyboard activation of search. They also check filter state and reset, states of cancelled tasks, keyboard zoom of screenshots, and the Flatpak widget path. You must still do a manual pass with Orca before a release. Only a person can judge the quality of the announcements from the accessibility tree.
