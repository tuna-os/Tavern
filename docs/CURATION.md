# Catalog curation

`data/curation.json` is Tavern's versioned, declarative recommendation feed. TunaOS can update it without shipping executable content or HTML.

Each section requires a unique `id`, a title, `package_type` (`formula` or `cask`), and an ordered package list. Optional fields are:

- `summary`: plain text, at most 240 characters;
- `link`: an HTTPS editorial link;
- `platforms`: `linux` and/or `darwin`;
- `starts_at` and `ends_at`: inclusive UTC dates in `YYYY-MM-DD` format.

The client limits the response to 128 KiB, validates every field, de-duplicates package names, and caps section/package counts. Invalid, missing, future, expired, or platform-inapplicable content is ignored. A validated stale cache is used offline, followed by built-in analytics-ranked defaults.

Remote curation is data only. Do not add scripts, arbitrary HTML, local paths, or non-HTTPS links. Changes receive the same repository review and signed-release provenance as application source.
