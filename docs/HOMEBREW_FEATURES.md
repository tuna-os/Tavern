# Homebrew tools in Tavern

Open **Maintenance** from the main menu. These tools run only on request.
Use Homebrew 7 for the full feature set. Unsupported commands show their
error output; Tavern does not replace them with a different command.

## Security

**Scan Installed Formulae** runs `brew vulns --json` against OSV.dev.
Homebrew sends package source and version information to that service.
Tavern shows open advisories, severity, fixed versions, and formula patches.
It also shows skipped formulae and warnings from stderr.

This scan does not cover casks, Flatpaks, or language packages. Older kegs
without an SBOM can have uncertain coverage. A report with no advisories is
not proof that all installed software is safe. Use **View Scan Output** to
inspect and copy the full report. Tavern does not install fixes automatically.

## Install previews and tasks

Package install buttons first run `brew install --dry-run` with the same
package type and tap as the real command. Choose **Install** to queue it.
If older Homebrew rejects this flag, the dialog offers **Install Without Preview**.
Other preview errors do not enable the install button.

Service controls, Brewfile installs, and disk cleanup share the task queue.
The task panel supports cancellation and a copyable output snapshot.
Review local paths and account details before you share command output.

## Services and disk space

Services use the current user account, never `sudo` or system scope.
Start registers a service at login; stop unregisters it. Restart can interrupt
clients. Homebrew retains the environment settings for each service.
Tavern does not edit those override files.

Cleanup and autoremove first show Homebrew's dry-run output. Each action needs
confirmation. Homebrew recalculates targets when the task runs, so the final
list can differ from the preview. Removed files do not go to Trash.

## Brewfiles

To open a Brewfile is to view it, not to add taps or run its Ruby code.
Tiles are a partial display, not a complete interpretation of the file.
Use **View Complete Brewfile** to inspect all source and options.

Install uses `brew bundle install --no-upgrade --file PATH`. Homebrew handles
Cargo, uv, npm, editor extensions, and other supported entry types.
Tavern does not rewrite source or omit entries after a metadata lookup fails.
The task checks that the file has not changed since review.

A Brewfile can execute arbitrary Ruby. Both install and dependency inspection
need explicit trust confirmation, even though `brew deps --brewfile` is a
preview. Trust also extends to other files the Brewfile loads.
Removal covers only the formulae and casks shown in its confirmation dialog.
It leaves taps and other package managers alone. `brew bundle cleanup` is
not an inverse install: it can remove packages outside the Brewfile.

## Diagnostics and old versions

Doctor uses Homebrew 7 JSON reports, with a text fallback for older Homebrew.
Suggested commands remain text; Tavern does not execute them.
**View Homebrew Configuration** shows `brew config`, with Landlock details
when the host supports them.

The tool for historical formulae runs `brew version-install` after
confirmation. It can create a personal tap and extract a formula from Git
history. Extracted formulae receive no automatic security fixes; you own their
maintenance. Prefer a maintained versioned formula when one exists.
This action does not pin the installed version or install casks.

Command and report contracts follow [Homebrew 7.0.0](https://github.com/Homebrew/brew/tree/7.0.0/Library/Homebrew).
See also the [Homebrew manual](https://docs.brew.sh/Manpage).
