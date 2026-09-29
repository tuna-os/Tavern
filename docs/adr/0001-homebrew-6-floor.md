# Tavern targets only Homebrew ≥ 6.0.0

Tavern is a pre-1.0 desktop app with 0 packaged users. Compatibility with both the Homebrew 5.x and 6.0.0 API response formats adds complexity for no real user. The same is true of support for two `brew` CLI behaviors. Anyone who runs Tavern from source can upgrade Homebrew. When the API schema changes, we update the code to match the current version and drop support for older releases.
