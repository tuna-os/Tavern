# Cache lifecycle

Tavern keeps metadata and media below the platform cache directory (`$XDG_CACHE_HOME/tavern` on Linux). Tavern clears the directory when the cache schema changes.

- Tavern refreshes catalogs after 12 hours, curation after 6 hours, and tap metadata after 24 hours.
- Version history has a 24-hour TTL. Doctor reports stay in memory for one hour.
  Run Again forces a new check, and failed checks do not renew the cache.
- Stale catalog data remains usable while Tavern refreshes it or the machine is offline.
- JSON writes are atomic. Tavern removes corrupt JSON and does not parse it as an empty catalog.
- Reads update access time. Under the 256 MiB quota, eviction removes the least recently used files first.
- Tavern checks paths before reads, writes, eviction, or cache reset. Operations cannot escape Tavern's directory.

Preferences shows the current cache size and offers **Clear Cache**. A cache reset affects only downloaded metadata and images. It never uninstalls packages or removes Homebrew state.
