# Cache lifecycle

Tavern keeps metadata and media below the platform cache directory (`$XDG_CACHE_HOME/tavern` on Linux). Tavern clears the directory when the cache schema changes.

- Tavern refreshes catalogs after 12 hours, curation after 6 hours, and tap metadata after 24 hours.
- Version history has a 24-hour TTL. Doctor reports stay in memory for one hour.
  Run Again forces a new check. A failed check does not renew the cache.
- Stale catalog data remains usable while Tavern refreshes it or the machine is offline.
- JSON writes are atomic. Tavern removes corrupt JSON, so it does not read it as an empty catalog.
- Reads update access time. When the cache is over its quota of 256 MiB, Tavern first evicts the files that it used least recently.
- Tavern resolves and checks each path before a read, write, eviction, or clear. Thus no cache operation can go outside Tavern's directory.

Preferences shows the current cache size and offers **Clear Cache**. A clear affects only downloaded metadata and images; it never uninstalls packages or removes Homebrew state.
