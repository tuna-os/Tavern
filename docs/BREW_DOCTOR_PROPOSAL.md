# Brew Doctor Implementation Proposal

This document gives the design and the plan for the **Brew Doctor** feature
in Tavern. Some of the patterns come from BrewUI, the official Homebrew app
for macOS.

---

## 1. Overview and Goals

Homebrew has a diagnostic command, `brew doctor`. It checks the local
installation for problems in the configuration, unlinked formulae,
old packages and environments that Homebrew does not support.

The goals for Brew Doctor in Tavern are:
1. **Accurate diagnosis**: Show each Homebrew diagnostic with a clear severity.
   The severity comes from the support tier.
2. **Safe fixes**: Let users run safe, verified fixes from the user interface.
   Each fix needs approval from the user.
3. **Safety limits**: Run only commands that are on a strict allowlist.
   Never run administrative commands (`sudo`) or shell scripts with many steps.
4. **Stable user experience**: Keep the selected issue and the UI context.
   Do this when a check runs again in the background or a task completes.
5. **Report export**: Let users see, copy and export the raw output of
   the diagnostic, for use in a bug report.

---

## 2. Ideas from BrewUI

BrewUI, the Homebrew client for macOS, has a tested model for Homebrew
diagnostics.

### UI States and Layout
BrewUI shows the diagnostic in one of four states:
- **Progress**: A progress indicator shows while `brew doctor` runs.
- **Healthy**: A message tells the user that Homebrew found no problems.
- **Issues**: A list shows the issues in groups by severity. A detail pane
  shows the selected issue.
- **Failed**: The page shows the error and a retry action. It keeps the
  previous report.

### Two Runs
BrewUI runs `brew doctor` two times:
1. **Structured run** (`brew doctor --json`): This run gives the issues,
   the support tiers and the data for each fix.
2. **Transcript run** (plain `brew doctor`): This run keeps all of the output,
   stderr messages too. The raw view and the clipboard use this output.

### The Rule for Fixes
BrewUI has a strict limit for automatic fixes. A fix can run from the app
only when all of these conditions are true:
- The fix has only one command.
- The command starts with `brew`.
- The app can get the argv arguments from the command.
- The command does not use `sudo`.

A fix that needs administrator access (`needsAdmin`) or has many steps is
text that the user can copy. The app marks it "runs in Terminal".

### A Hash to Keep the Selection
The selection must not move or clear when the user fixes an issue or when the
list loads again. For this, BrewUI makes a hash of the title and the body of
each issue. The detail view follows the selected hash through each new check.

---

## 3. Status in Tavern

Tavern has the first phases of this proposal:

### Phase 1: Doctor Page That Only Reads (PR #176)
- **UI**: Added `TavernDoctorPage` (`src/doctor_page.py`, `src/doctor-page.blp`).
  It has Run Check and Run Again controls, a spinner and status labels.
  It also has a card for each issue that expands, and a raw output view.
- **Separate service**: Added `DoctorService` (`src/doctor.py`). It does not
  use GTK. It keeps each report in memory for 1 hour, and it runs only one
  check at a time.
- **No block of the UI**: A background daemon thread does the work.
  `GLib.idle_add` sends the result to the main loop.
- **Exit status**: The service accepts return code 1 when there are warnings.
  It shows a failure of the command as different from a warning.
- **Clipboard**: One click copies the full output of the diagnostic.

### Homebrew 7 Structured Output (PR #177)
- **JSON**: Added `parse_json_report()` for the Homebrew 7 `Finding#to_h`
  format, the support tiers (Tier 1 to 3, unsupported) and the fix data.
- **Fallback for Homebrew 6**: Kept the regex parser for text. Tavern uses it
  when an older Homebrew does not accept `--json`.
- **Configuration view**: Added **View Homebrew Configuration**. It shows the
  output of `brew config`, with the Landlock sandbox data when it is available.
- **Base for the task queue**: Added `submit_command()` to `TaskManager`.
  It accepts argument lists for approved maintenance commands.

---

## 4. Phase 2: Fixes That Run, and a Stable Selection

The next phase adds safe fixes to the task pipeline of Tavern.

### Allowlist for Fix Commands
A **Fix** button shows only for a fix command that matches one of these
patterns:
- `brew link <formula>`
- `brew link --overwrite <formula>`
- `brew unlink <formula>`
- `brew cleanup`
- `brew autoremove`

A fix with semicolons, shell pipes, subshells, variable expansion or `sudo`
stays as text. It does not run.

### Task Queue
- Fix actions go to `TaskManager.submit_command()`.
- A key for each fix (for example `doctor-fix:<command>`) stops two runs of
  the same fix at the same time.
- The existing `task-changed` GObject signal tracks the operations that run.
- Each row shows a spinner. The row shows an error message if the fix fails.

### New Check After a Fix, and Selection Tracking
- After a fix task is successful, Tavern starts a new doctor check in the
  background (`force=True`).
- Each issue gets a SHA-256 `content_id` from its title and body.
- The UI keeps the active `content_id`. If the fixed issue is not in the new
  report, the selection moves to the next issue. If no issues remain, the page
  shows the healthy state.

---

## 5. Phase 3: Other Parity Items and Export

### Report Export
- Add an **Export Report** action. It saves the diagnostic summary and the
  raw output to a local text file.
- Remove private local paths, or ask the user to confirm before the save.

### Task Panel
- Give maintenance tasks and doctor tasks an origin tag. The Task Panel can
  then sort and filter them together with package installs and upgrades.

### Terminal Instructions for Admin Tasks
- Some fixes need more permissions, for example to change system directories.
  For these, show a command card with a copy button.
- The card tells the user to run the command in a terminal.

---

## 6. Security and Sandbox Rules

1. **No shell**: All Homebrew commands go through `_brew_cmd()` as lists of
   arguments. Never use `shell=True`.
2. **Flatpak limits**: In Flatpak, Tavern uses `flatpak-spawn --host brew`.
   Tavern never asks for more privileges.
3. **No automatic fixes**: Each fix needs an action from the user.
   Tavern never runs a fix in the background on its own.
4. **No ANSI codes**: Remove the terminal escape codes from the output before
   Tavern shows it. This stops terminal injection.
