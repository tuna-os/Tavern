Harden the README view: render it under a restrictive Content-Security-Policy, strip raw HTML elements that load content or navigate, and only open http, https and mailto links externally.
