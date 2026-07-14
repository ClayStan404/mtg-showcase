# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public issue.

Instead, email the repository owner directly. You can find the contact information on the [GitHub profile](https://github.com/ClayStan404).

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

You should receive a response within 48 hours.

## Scope

This is a static website (GitHub Pages) with no backend, database, or user authentication. The attack surface is limited to:

- **CI/CD pipeline**: GitHub Actions workflows that fetch data from WPS and deploy to Pages
- **Frontend**: Vanilla JS/HTML/CSS, no build step, no user input processing beyond localStorage
- **Data scripts**: Python scripts that parse Excel files and fetch from Scryfall API

## Dependencies

- Python dependencies are monitored via Dependabot (pip ecosystem, weekly checks)
- GitHub Actions versions are monitored via Dependabot (github-actions ecosystem, weekly checks)
