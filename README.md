# Sci-Hub MCP Server — maintained fork

**English** | [简体中文](README.zh-CN.md)

A local MCP server for finding academic papers by DOI, title or keyword, retrieving Crossref metadata, and downloading PDFs.

This fork of [JackKuo666/Sci-Hub-MCP-Server](https://github.com/JackKuo666/Sci-Hub-MCP-Server) fixes PDF discovery and download failures in the original implementation. It keeps the five MCP tool names and adds title disambiguation, mirror fallback and PDF content checks. See [CHANGELOG.md](CHANGELOG.md) and [NOTICE.md](NOTICE.md) for changes and attribution.

## Requirements

- Python **3.12** and Git. The checked-in dependency lock targets Python 3.12.
- Network access to Crossref and at least one configured mirror/PDF host. No API key is required.
- A client that supports local MCP servers over stdio, such as Codex or Claude Desktop.

The first release was tested locally on Windows 10 with Python 3.12.10. GitHub Actions checks installation, offline regression tests and MCP startup on Windows, Ubuntu and macOS with Python 3.12. Network availability is not tested in CI.

## Install

Clone the stable release:

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/EvanZ-2001/Sci-Hub-MCP-Server.git
cd Sci-Hub-MCP-Server
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -B verify_release.py
```

Linux/macOS:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -B verify_release.py
```

Alternatively, with [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12
uv pip sync requirements.lock.txt
```

Use `requirements.lock.txt` to reproduce the release. `requirements.txt` contains the direct dependency ranges for development. The legacy `scihub` package is no longer required.

## Mirrors and proxy

No settings file is required. The default mirrors are tried in order:

1. `https://www.sci-hub.st`
2. `https://sci-hub.su`
3. `https://www.sci-hub.ru`
4. `https://sci-hub.red`
5. `https://sci-hub.box`
6. `https://sci-hub.al`
7. `https://sci-hub.mk`
8. `https://sci-hub.ee`

These are fallback endpoints from the previously tested mirror list, not an availability guarantee. A mirror can return a PDF on one request and a verification page on the next. A reachable homepage does not guarantee a usable PDF.

For custom mirrors or a proxy, copy `settings.example.json` to `settings.local.json` beside `sci_hub_search.py`. On PowerShell use `Copy-Item settings.example.json settings.local.json`; on Linux/macOS use `cp settings.example.json settings.local.json`.

Edit the copy:

```json
{
  "mirrors": [
    "https://www.sci-hub.st",
    "https://sci-hub.su",
    "https://www.sci-hub.ru",
    "https://sci-hub.red",
    "https://sci-hub.box",
    "https://sci-hub.al",
    "https://sci-hub.mk",
    "https://sci-hub.ee"
  ],
  "proxy": ""
}
```

Keep `proxy` empty unless you need an explicit HTTP proxy. For example, `http://127.0.0.1:7890` is only appropriate if a proxy is actually listening on that port on your computer. The server does not start or configure proxy software. An explicit proxy applies only to this server's HTTP sessions and disables inherited proxy settings for those sessions.

Without an explicit proxy, Requests uses its standard environment configuration, including `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY`. A desktop MCP client may not inherit your terminal's environment; put the proxy in `settings.local.json` or the client's server environment when needed.

Mirror precedence is: nonempty `settings.local.json` mirror list → comma-separated `SCIHUB_MIRRORS` environment variable → built-in defaults. Only HTTPS mirror URLs are used. Configuration is read relative to the source file, independently of the client's working directory. `settings.local.json` is ignored by Git; do not commit personal settings.

## Connect to Codex

Following the [official Codex MCP configuration documentation](https://developers.openai.com/codex/mcp), add a server entry to `~/.codex/config.toml`. Replace the example paths with **absolute paths on your computer**. Update an existing `scihub` entry instead of adding a duplicate.

Windows example:

```toml
[mcp_servers.scihub]
command = 'C:\path\to\Sci-Hub-MCP-Server\.venv\Scripts\python.exe'
args = ['-B', '-u', 'C:\path\to\Sci-Hub-MCP-Server\sci_hub_server.py']
cwd = 'C:\path\to\Sci-Hub-MCP-Server'
startup_timeout_sec = 30
tool_timeout_sec = 180
enabled = true

[mcp_servers.scihub.env]
PYTHONUTF8 = "1"
PYTHONIOENCODING = "utf-8"
PYTHONDONTWRITEBYTECODE = "1"
```

On Linux/macOS use `/absolute/path/Sci-Hub-MCP-Server/.venv/bin/python` for `command`, `/absolute/path/Sci-Hub-MCP-Server/sci_hub_server.py` in `args`, and `/absolute/path/Sci-Hub-MCP-Server` for `cwd`. Keep the timeout and encoding settings above. Restart the server/client after configuration changes and open a new chat if the old tool catalog is still shown.

## Other MCP clients

For a client using a JSON `mcpServers` configuration, replace these paths with your own (use forward slashes or escaped backslashes on Windows):

```json
{
  "mcpServers": {
    "scihub": {
      "command": "C:/path/to/Sci-Hub-MCP-Server/.venv/Scripts/python.exe",
      "args": ["-B", "-u", "C:/path/to/Sci-Hub-MCP-Server/sci_hub_server.py"],
      "env": {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

On Linux/macOS substitute the `.venv/bin/python` executable and absolute script path. If the client has a tool timeout setting, allow at least 180 seconds for searches. Use an absolute download path whose parent directory already exists.

The server starts with `python sci_hub_server.py` under the installed environment and communicates over stdin/stdout. It does not expose an HTTP port. Running it in a terminal without an MCP client will wait for protocol messages. Logs go to stderr.

## Tools

| Tool | Inputs | Result |
| --- | --- | --- |
| `search_scihub_by_doi` | `doi` (a DOI or DOI URL) | Verified PDF URL or diagnostic failure state |
| `search_scihub_by_title` | `title`; optional `author`, `year`, `journal` | Matching paper or candidates for disambiguation |
| `search_scihub_by_keyword` | `keyword`; `num_results` from 1 to 20 (default 10) | Crossref candidates with successful PDF lookups first |
| `get_paper_metadata` | `doi` | Crossref title, authors, year, journal and any publisher PDF URL |
| `download_scihub_pdf` | `pdf_url`, `output_path` | Download result message |

Search `status: success` means the candidate response began with `%PDF-`; `pdf_verified: true` confirms this content check. It does not certify the full PDF's identity. If the source page declares a different DOI, that page is rejected. Metadata lookup success means Crossref returned metadata; its publisher PDF URL is **not** verified.

Title and keyword searches use Crossref to identify DOI candidates before resolving PDFs. Ambiguous titles return candidates; specify a DOI or author/year/journal to choose the intended publication. `num_results` limits returned records, not the number of guaranteed PDFs. Unresolved records retain metadata and diagnostics.

Searches have a 140-second time budget, with shorter budgets per title/keyword candidate. Network timeouts and mirror challenges can still affect completion time. Downloads use a temporary `.part` file and replace the target only after transfer succeeds. The parent directory must already exist. Existing target files are replaced on success and preserved on failure.

Example requests:

- Find a verified PDF link for DOI `10.1371/journal.pmed.0020124`.
- Find “Why Most Published Research Findings Are False”, journal PLoS Medicine, year 2005.
- Search for `research data sharing`, return at most three records, and show which have verified PDF links.
- Download the returned PDF to an absolute path of your choice.

## Verify and troubleshoot

Run from the repository root with the installed Python environment:

```sh
python -B -m unittest test_local_compat -v
python -B verify_release.py
```

These checks are offline. `verify_release.py` initializes a real stdio MCP connection and checks all five tools and their descriptions/parameters.

To also check Crossref, DOI/title/keyword search, download and a fresh server process:

```sh
python -B verify_release.py --online
```

Use `.venv/bin/python` or `.\.venv\Scripts\python.exe` instead of `python` if the environment is not activated. The online check uses an open-access PLOS sample and writes a PDF, diagnostics and a report under `verification-output/` (ignored by Git). It can take several minutes. A failure includes the failed step; inspect the report/log and your proxy/mirror configuration. An offline pass alone does not prove network access.

- `blocked`: a mirror returned a challenge page. The server tries other mirrors; it does not solve verification challenges.
- `unavailable` / `not_found` / `timeout`: inspect `diagnostics`; check mirror access, paper availability and proxy settings.
- TLS errors: check local certificate/proxy configuration. TLS certificate verification stays enabled.
- No tools in the client: check the absolute interpreter/script paths, installed dependencies and client logs, then restart the server.

## License and attribution

MIT, as declared by the upstream README. This fork supplies the standard [LICENSE](LICENSE) text and records its provenance in [NOTICE.md](NOTICE.md). Original author: [JackKuo666](https://github.com/JackKuo666). Referenced contributions by xuio, mikhailnov and HyperD1ve are credited there.

This tool is for research purposes only. Please respect copyright laws and use this tool responsibly. The authors do not endorse or encourage copyright infringement. The repository and release contain software, not paper collections.
