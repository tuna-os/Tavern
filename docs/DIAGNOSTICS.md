# Local diagnostics

Tavern writes warnings and errors to stderr by default. Use `TAVERN_LOG=info`
for routine detail or `TAVERN_LOG=debug` for verbose output.
`TAVERN_LOG_FILE=/path/to/log` also writes to a local file at that log level.
`TAVERN_PROFILE=1` enables duration reports and the INFO log level.

For a source build, run `TAVERN_LOG=debug TAVERN_PROFILE=1 ./run.sh`.
For Flatpak, run:

```bash
flatpak run --env=TAVERN_LOG=debug --env=TAVERN_PROFILE=1 org.tunaos.tavern
```

The helpers live in `src/logging_util.py`: `get_logger`, `profile`, and
`log_timing`. Tavern has no remote telemetry exporter. Review logs for local
paths and private tap names before you attach them to an issue.

For a bug report, include the app version, install channel, OS, steps to
reproduce, expected result, actual result, and relevant logs.
For a release failure, also include the workflow URL and source commit.
