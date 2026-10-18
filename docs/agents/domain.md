# Domain Docs

How the engineering skills should consume this repo's domain documentation when they explore the codebase.

## Before exploring, read these

- **`AGENTS.md`** at the repo root — the layout of the repo, its test gates, and its release ownership.
- **`README.md`** at the repo root — the domain overview (a Homebrew client for formulae, casks, and taps).
- **`docs/adr/`** — read the ADRs that touch the area of your work.
- **The domain deep-dive**, when the work touches it: [`docs/CACHE.md`](../CACHE.md), [`docs/CURATION.md`](../CURATION.md), [`docs/RELEASING.md`](../RELEASING.md), [`docs/ACCESSIBILITY.md`](../ACCESSIBILITY.md), [`docs/HOMEBREW_FEATURES.md`](../HOMEBREW_FEATURES.md).

Tavern keeps its domain context in these files. It has no `CONTEXT.md` glossary at the repo root.

## File structure

Single-context repo:

```
/
├── AGENTS.md
├── README.md
├── ROADMAP.md
├── docs/
│   ├── adr/
│   │   └── 0001-homebrew-6-floor.md
│   ├── CACHE.md
│   ├── CURATION.md
│   ├── RELEASING.md
│   ├── ACCESSIBILITY.md
│   └── agents/
├── src/
└── tests/
```

## Use the project's vocabulary

When your output names a domain concept (in an issue title, proposal, hypothesis, or test name), use the terms defined in the domain docs above.
Tavern's domain is small (formulae, casks, taps, caches, Brewfiles) — do not drift to synonyms the existing docs do not use.

If you need a term that the docs do not define, that is a signal.
Either the concept maps to something already named, or there is a real gap to document or note for a maintainer.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly instead of a silent override:

> _Contradicts ADR-0001 (Homebrew ≥ 6.0.0) — but worth a reopen because…_
