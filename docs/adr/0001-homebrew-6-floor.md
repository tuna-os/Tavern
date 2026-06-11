# Tavern targets only Homebrew ≥ 6.0.0

Tavern is a pre-1.0 desktop app with 0 packaged users. Maintaining dual-schema compatibility with both the Homebrew 5.x and 6.0.0 API response formats (or supporting two `brew` CLI behaviors) adds complexity for no real user — anyone running Tavern from source can upgrade Homebrew. When the API schema changes, we update the code to match the current version and drop support for older releases.
