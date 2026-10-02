# Security Policy

Tavern is a Homebrew client for Linux that manages package installation and system packages. Security vulnerabilities in Tavern could impact user systems, so we take reports seriously.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.** Instead, use GitHub's private vulnerability reporting:

1. Go to the [Tavern security advisories page](https://github.com/tuna-os/Tavern/security/advisories/new).
2. Click **Report a vulnerability** and draft a security advisory.
3. Include:
   - Affected component (package manager integration, privilege handling, UI, etc.)
   - Minimal steps to reproduce
   - Impact and severity (privilege escalation, code execution, data leakage, etc.)
   - Suggested fix, if you have one

Alternatively, email the maintainers through a GitHub Security Advisory draft if the affected version is not yet released.

## What to report

Report vulnerabilities in:

- **Privilege escalation**: Tavern running with elevated privileges when it shouldn't, or allowing unprivileged users to perform privileged operations
- **Package source spoofing**: Unsafe handling of Homebrew taps, repositories, or package sources
- **Dependency vulnerabilities**: Insecure handling of untrusted packages or malicious dependency chains
- **Credential leaks**: Insecure storage or transmission of authentication tokens, API keys, or credentials
- **Unsafe command execution**: Shell injection or unsafe subprocess handling when invoking Homebrew
- **UI vulnerabilities**: HTML injection, XSS, or other issues in the GTK interface
- **Supply chain issues**: Unsigned artifacts, unpinned dependencies, or tampered releases

## Out of scope

Do not report vulnerabilities in:

- **Homebrew upstream**: The Homebrew project itself, its formulae, or core package manager. Report to [Homebrew Security](https://github.com/Homebrew/brew/security/advisories).
- **Third-party packages**: Vulnerabilities in packages installed *through* Homebrew. Report to the package maintainer.
- **System libraries**: GTK, Libadwaita, Python, or the Linux kernel. Report to the relevant upstream project.
- **Homebrew taps**: Vulnerabilities in third-party taps. Report to the tap maintainer.

## Response timeline

We aim to:

- **Acknowledge** your report within **5 business days**
- **Triage** the vulnerability and confirm reproducibility within **10 days**
- **Fix and release** a patch through the normal release pipeline, usually within **30 days** of triage
- **Coordinate disclosure**: we prefer coordinated disclosure. Please give us a reasonable window (at least 30 days after we confirm a fix is ready) before publishing details publicly

## Disclosure

Once a fix is released, we will:

1. Publish a GitHub Security Advisory with CVE details (if applicable)
2. Add an entry to the CHANGELOG with the version and fix summary
3. Notify users through release notes and the Flatpak auto-update mechanism

If you discovered the vulnerability responsibly and wish to be credited, tell us in your report.

## Shared responsibility

Tavern is a frontend to Homebrew. The security boundary is:

- **Tavern handles**: UI, user authentication for Homebrew, dependency resolution UI, package caching
- **Homebrew handles**: Package signing, source verification, actual package installation, privilege escalation
- **Your system handles**: Local file permissions, sudo configuration, system security policies

A vulnerability in Tavern's UI does not automatically mean a vulnerability in Homebrew, and vice versa. We will triage reports based on where the issue actually lies and coordinate with Homebrew maintainers when needed.

## Questions or feedback

If you have questions about this policy or feedback on Tavern's security posture, open a public issue in the [Tavern tracker](https://github.com/tuna-os/Tavern/issues) or reach out to the maintainers.
