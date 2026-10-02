# Security Policy

Tavern is a Homebrew client for Linux. We take security reports seriously.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.** Use GitHub's private vulnerability reporting:

1. Go to [Tavern security advisories](https://github.com/tuna-os/Tavern/security/advisories/new).
2. Click **Report a vulnerability**.
3. Include:
   - Affected component
   - Steps to reproduce
   - Impact and severity
   - Suggested fix, if known

## In scope

- Privilege escalation
- Package source spoofing
- Dependency vulnerabilities
- Credential leaks
- Unsafe command execution
- UI vulnerabilities (injection, XSS)
- Supply chain issues

## Out of scope

- Homebrew upstream — report to [Homebrew Security](https://github.com/Homebrew/brew/security/advisories)
- Third-party packages — report to the package maintainer
- System libraries (GTK, Python, kernel) — report upstream
- Homebrew taps — report to the tap maintainer

## Timeline

- Acknowledge: 5 business days
- Triage: 10 days
- Fix and release: 30 days
- Prefer coordinated disclosure (30 days before public details)

## After a fix

- Publish GitHub Security Advisory
- Update CHANGELOG
- Notify users via release notes
- Credit reporter if requested

## Shared responsibility

- Tavern: UI and package caching
- Homebrew: package signing and installation
- Your system: file permissions and sudo

## Questions

Open a [public issue](https://github.com/tuna-os/Tavern/issues) or contact the maintainers.
