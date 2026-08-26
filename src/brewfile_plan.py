"""Pure planning helpers for Brewfile bulk operations.

This module deliberately has no GTK, threading, subprocess, or filesystem
dependencies.  The Brewfile page owns presentation and scheduling; this layer
owns the policy for excluding entries whose discovery failed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BrewfilePlan:
    taps: tuple[object, ...]
    formulae: tuple[str, ...]
    casks: tuple[str, ...]
    flatpaks: tuple[str, ...]

    def render(self) -> str:
        """Render the filtered plan as a Brewfile accepted by ``brew bundle``."""
        lines = []
        for tap in self.taps:
            if isinstance(tap, dict):
                name = tap['name']
                trusted = tap.get('trusted', False)
            else:
                name = tap
                trusted = False
            suffix = ', trusted: true' if trusted else ''
            lines.append(f'tap "{name}"{suffix}')

        lines.extend(f'brew "{name}"' for name in self.formulae)
        lines.extend(f'cask "{name}"' for name in self.casks)
        lines.extend(f'flatpak "{app_id}"' for app_id in self.flatpaks)
        return '\n'.join(lines) + ('\n' if lines else '')


def build_plan(parsed_data, *, tap_errors=(), cask_errors=(), flatpak_errors=()):
    """Return the executable subset of parsed Brewfile data."""
    tap_errors = set(tap_errors)
    cask_errors = set(cask_errors)
    flatpak_errors = set(flatpak_errors)

    taps = tuple(
        tap for tap in parsed_data.get('taps', [])
        if (tap['name'] if isinstance(tap, dict) else tap) not in tap_errors
    )
    return BrewfilePlan(
        taps=taps,
        formulae=tuple(parsed_data.get('formulae', [])),
        casks=tuple(cask for cask in parsed_data.get('casks', []) if cask not in cask_errors),
        flatpaks=tuple(app_id for app_id in parsed_data.get('flatpaks', []) if app_id not in flatpak_errors),
    )
