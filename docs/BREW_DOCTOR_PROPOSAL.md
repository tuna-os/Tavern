# Brew Doctor Implementation Proposal

This document outlines the architecture and implementation proposal for the
**Brew Doctor** feature in Tavern, incorporating inspirations and design patterns
from the official [BrewUI](https://github.com/brewui/brewui) macOS application.

---

## 1. Overview and Goals

Homebrew includes a diagnostic command, `brew doctor`, which checks the local
installation for configuration issues, unlinked formulae, obsolete packages,
and unsupported environments.

The goals for Brew Doctor in Tavern are:
1. **Accurate Diagnosis**: Present Homebrew diagnostics with clear severity
   levels derived from support tiers.
2. **Safe Remediations**: Allow users to run safe, verified remediations directly
   from the user interface with explicit approval.
3. **Safety Boundaries**: Restrict executable commands to a strict allowlist.
   Never execute administrative commands (`sudo`) or multi-step shell scripts.
4. **Stable User Experience**: Maintain issue selection and UI context across
   background re-checks and task completions.
5. **Report Sharing**: Enable users to view, copy, and export raw diagnostic
   transcripts for troubleshooting.

---

## 2. Inspirations from BrewUI

The [BrewUI](https://github.com/brewui/brewui) macOS client provides a tested
interaction model for Homebrew diagnostics:

### UI States and Layout
BrewUI projects four distinct diagnostic states:
- **Loading**: Displays progress indicator with "Running brew doctor…".
- **Healthy**: Shows "No problems found" with an installation reassurance note.
- **Issues**: Displays findings grouped by severity in a list, alongside an
  issue detail pane.
- **Failed**: Surfaces execution errors with a retry action without clearing the
  prior report.

### Double-Run Pattern
BrewUI executes `brew doctor` in two complementary passes:
1. **Structured run** (`brew doctor --json`): Delivers structured findings,
   support tiers, and remediation metadata.
2. **Transcript run** (plain `brew doctor`): Captures complete verbatim output
   for the raw view and clipboard export, preserving stderr messages.

### The Runnable Rule
BrewUI establishes a strict boundary for automated fixes:
- A remediation is runnable **only** if it consists of a single command step,
  begins with `brew`, contains extractable argv arguments, and requires no `sudo`.
- Any remediation requiring administrator access (`needsAdmin`) or multiple steps
  remains copy-only, marked with "runs in Terminal".

### Content Hashing for Selection Stability
To prevent the selection from jumping or resetting when an issue is resolved or
when the list reloads, BrewUI computes a deterministic hash of the issue title
and body. The detail view tracks the selected hash across re-checks.

---

## 3. Implementation Status in Tavern

Tavern has implemented the foundational phases of this proposal:

### Phase 1: Read-Only Doctor Page (PR #176)
- **UI Surface**: Added `TavernDoctorPage` (`src/doctor_page.py`, `src/doctor-page.blp`)
  with Run Check / Run Again controls, spinner, status labels, expandable finding
  cards, and raw output display.
- **Decoupled Service**: Added `DoctorService` (`src/doctor.py`) independent of
  GTK, with an in-memory cache TTL of 1 hour and concurrent run serialization.
- **Non-blocking Execution**: Worker runs on a background daemon thread with
  main-loop delivery via `GLib.idle_add`.
- **Exit Status Tolerance**: Tolerates returncode 1 when diagnostic warnings
  are present, distinguishing true command failures from diagnostic findings.
- **Clipboard Support**: One-click copying of verbatim diagnostic transcripts.

### Homebrew 7 Structured Findings (PR #177)
- **JSON Parsing**: Added `parse_json_report()` supporting Homebrew 7 `Finding#to_h`
  structures, support tiers (Tier 1–3, unsupported), and remediation metadata.
- **Pre-7 Fallback**: Retained regex-based text parsing fallback for older
  Homebrew installations that reject `--json`.
- **Configuration View**: Added **View Homebrew Configuration** to display
  `brew config` output, including Landlock sandbox diagnostics when supported.
- **Task Queue Foundation**: Extended `TaskManager` with `submit_command()` to
  accept verified argument sequences for maintenance operations.

---

## 4. Phase 2: Runnable Fix Actions & Selection Stability

The next phase integrates safe remediations into Tavern's task pipeline:

### Fix Command Allowlist
Only remediation commands that strictly match approved patterns will expose
a **Fix** button:
- `brew link <formula>`
- `brew link --overwrite <formula>`
- `brew unlink <formula>`
- `brew cleanup`
- `brew autoremove`

Remediations containing semicolons, shell pipelines, subshells, variable
expansions, or `sudo` will remain non-executable text.

### Task Queue Integration
- Fix actions submit to `TaskManager.submit_command()`.
- Use a deduplication key (e.g. `doctor-fix:<command>`) to prevent duplicate
  in-flight execution of the same repair step.
- Track running operations using the existing `task-changed` GObject signal.
- Display row-level spinners and inline error messages on failure.

### Post-Fix Re-scan and Selection Tracking
- When a fix task completes successfully, Tavern triggers a background doctor
  refresh (`force=True`).
- Issues compute a SHA-256 `content_id` from their title and body.
- The UI maintains the active `content_id`. If the resolved issue disappears,
  the selection smoothly advances to the next finding or transitions to the
  healthy state.

---

## 5. Phase 3: Parity Extras & Export

### Diagnostic Export
- Provide an **Export Report** action allowing users to save the complete
  diagnostic summary and raw transcript to a local text file.
- Strip sensitive local paths or provide user confirmation before saving.

### Task Panel Integration
- Tag maintenance and doctor tasks with an origin identifier so the Task Panel
  can categorize and filter them alongside package installs and upgrades.

### Terminal Guidance for Admin Tasks
- When a finding suggests actions requiring elevated permissions (e.g. modifying
  system directories), render a dedicated command card with a copy button and
  an explicit note that the command must be run manually in a terminal.

---

## 6. Security and Sandboxing Rules

1. **No Shell Execution**: All Homebrew invocations must pass through
   `_brew_cmd()` as discrete argument lists. Never use `shell=True`.
2. **Flatpak Confinement**: When running inside Flatpak, execution uses
   `flatpak-spawn --host brew`. Tavern never requests elevated privileges.
3. **No Automatic Execution**: Remediations must always require explicit user
   interaction. Tavern never automatically runs fixes in the background.
4. **ANSI Stripping**: Verbatim output must strip terminal escape sequences
   before presentation to prevent terminal injection.
