# Changelog

## v0.1.0 — 2026-10-23

First usable release of this fork, based on upstream commit `aacb5c2`.

- Replace the legacy `scihub` dependency with direct Requests/BeautifulSoup parsing of object, iframe, embed, metadata and download-button PDF links.
- Resolve relative URLs, check PDF content before reporting search success, and reject pages declaring a different DOI.
- Add mirror fallback, request budgets and diagnostic failure states while retaining TLS verification and stderr logging.
- Use Crossref title candidates with optional author/year/journal filters; return ambiguous matches for selection.
- Search additional keyword candidates, prefer verified PDFs and retain metadata for unresolved records.
- Stream downloads through a temporary file and preserve an existing destination on failure.
- Provide a personal-settings example, multi-mirror defaults, a Python 3.12 dependency lock with platform markers, and portable installation/MCP instructions.
- Include offline regression tests, a stdio MCP verification script with optional online acceptance checks, and Windows/Linux/macOS CI.
- Retain upstream Git history and credit the original author and referenced PR contributors; supply the MIT license text declared by upstream.

Mirror access remains network-dependent. See the README for proxy settings, verification commands and limitations.
