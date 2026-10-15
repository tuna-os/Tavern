# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

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

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as it appears in `README.md`, `AGENTS.md`, and the domain docs above. Tavern's domain is small (formulae, casks, taps, caches, Brewfiles) — don't drift to synonyms the existing docs don't use.

If you find yourself needing a term the docs don't define, that's a signal: either the concept maps to something already named (use that name) or there's a real gap (add it to the relevant doc, or note it for a maintainer).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (Homebrew ≥ 6.0.0) — but worth reopening because…_
