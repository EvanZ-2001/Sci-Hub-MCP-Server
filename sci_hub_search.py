"""Resolve Sci-Hub PDF links without downloading whole papers during search.

Parser/mirror handling adapted from upstream PRs #15 and #10. Keep TLS
verification, stderr logging and bounded requests from the local installation.
"""
import json
import logging
import os
from pathlib import Path
import re
import time
from difflib import SequenceMatcher
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)
SETTINGS_PATH = Path(__file__).with_name("settings.local.json")
DEFAULT_MIRRORS = (
    "https://www.sci-hub.st", "https://sci-hub.su", "https://www.sci-hub.ru",
    "https://sci-hub.red", "https://sci-hub.box", "https://sci-hub.al",
    "https://sci-hub.mk", "https://sci-hub.ee",
)
SEARCH_SECONDS = 140
REQUEST_TIMEOUT = (4, 12)


def load_settings():
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")) if SETTINGS_PATH.exists() else {}
    mirrors = settings.get("mirrors") or os.environ.get("SCIHUB_MIRRORS", ",".join(DEFAULT_MIRRORS)).split(",")
    normalized = []
    for mirror in mirrors:
        mirror = mirror.strip().rstrip("/")
        if not mirror.startswith(("http://", "https://")):
            mirror = "https://" + mirror
        if urlsplit(mirror).scheme == "https" and mirror not in normalized:
            normalized.append(mirror)
    settings["mirrors"] = normalized
    return settings


def create_session(settings=None):
    settings = settings if settings is not None else load_settings()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 SciHub-MCP/1.0", "Accept-Language": "en-US,en;q=0.9"})
    if settings.get("proxy"):
        # Explicitly configure this project; Codex may not forward shell proxy variables.
        session.trust_env = False
        session.proxies.update({"http": settings["proxy"], "https": settings["proxy"]})
    return session


def normalize_doi(value):
    value = unquote(value.strip())
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    if not re.fullmatch(r"10\.\d{4,9}/\S+", value, flags=re.I):
        raise ValueError("Provide a DOI or a https://doi.org/ DOI URL")
    return value.lower()


def _get(session, url, deadline, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("Search time budget exhausted")
    timeout = tuple(min(value, remaining / 2) for value in REQUEST_TIMEOUT)
    return session.get(url, timeout=timeout, verify=True, **kwargs)


def _read_prefix(response, deadline, limit):
    data = bytearray()
    for chunk in response.iter_content(chunk_size=min(1024, limit)):
        if time.monotonic() >= deadline:
            raise requests.Timeout("Search time budget exhausted")
        data.extend(chunk)
        if len(data) >= limit:
            break
    return bytes(data[:limit])


def parse_article(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for selector, attribute in [
        ('meta[name="citation_pdf_url"]', "content"),
        ("object[data]", "data"), ("iframe[src]", "src"), ("embed[src]", "src"),
        ('a[href]', "href"),
    ]:
        for element in soup.select(selector):
            value = element.get(attribute, "").strip()
            if element.name == "a" and not (".pdf" in value.lower() or element.has_attr("download")):
                continue
            candidate = urldefrag(urljoin(page_url, value))[0]
            if value and urlsplit(candidate).scheme == "https" and candidate not in candidates:
                candidates.append(candidate)
    # Parse literal download-button destinations; never execute page JavaScript.
    for element in soup.select("button[onclick]"):
        match = re.search(r"(?:location(?:\.href)?)\s*=\s*['\"]([^'\"]+)['\"]", element["onclick"])
        if match:
            candidate = urldefrag(urljoin(page_url, match.group(1)))[0]
            if urlsplit(candidate).scheme == "https" and candidate not in candidates:
                candidates.append(candidate)
    def meta(name):
        element = soup.find("meta", attrs={"name": name})
        return element.get("content", "").strip() if element else ""
    metadata = {
        "title": meta("citation_title"),
        "author": "; ".join(el.get("content", "") for el in soup.select('meta[name="citation_author"]')),
        "year": meta("citation_publication_date")[:4],
        "page_doi": meta("citation_doi"),
    }
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    text = soup.get_text(" ", strip=True).lower()
    blocked = any(marker in title for marker in (
        "проверка на робота", "are you", "robot", "just a moment", "ddos-guard", "attention required",
    )) or (not candidates and any(marker in text for marker in ("verify you are human", "checking your browser")))
    not_found = any(marker in text for marker in ("article not found", "paper not found", "статья не найдена"))
    status = "blocked" if blocked else "not_found" if not_found else "no_pdf_link"
    return candidates, metadata, status


def validate_pdf(session, url, page_url, deadline):
    with _get(session, url, deadline, stream=True,
              headers={"Range": "bytes=0-1023", "Referer": page_url}) as response:
        response.raise_for_status()
        prefix = _read_prefix(response, deadline, 1024)
        if not prefix.startswith(b"%PDF-"):
            raise ValueError("Candidate returned HTML or other non-PDF content")
        return urldefrag(response.url)[0]


def _resolve_doi(doi, session, mirrors, deadline):
    diagnostics = []
    for mirror in mirrors:
        if time.monotonic() >= deadline:
            diagnostics.append({"mirror": mirror, "status": "timeout"})
            break
        page_url = mirror + "/" + quote(doi, safe="/")
        try:
            with _get(session, page_url, deadline, stream=True) as response:
                body = _read_prefix(response, deadline, 2 * 1024 * 1024)
                page_url = response.url
                candidates, metadata, status = parse_article(body, page_url)
                if status == "blocked":
                    diagnostics.append({"mirror": mirror, "status": "blocked"})
                    continue
                if response.status_code == 404:
                    diagnostics.append({"mirror": mirror, "status": "not_found"})
                    continue
                response.raise_for_status()
                if body.startswith(b"%PDF-"):
                    candidates = [page_url]
                page_doi = metadata.pop("page_doi", "")
                if page_doi and normalize_doi(page_doi) != doi:
                    diagnostics.append({"mirror": mirror, "status": "doi_mismatch", "page_doi": page_doi})
                    continue
            candidate_errors = []
            for candidate in candidates[:6]:
                try:
                    pdf_url = validate_pdf(session, candidate, page_url, deadline)
                    return {"doi": doi, **metadata, "pdf_url": pdf_url, "page_url": page_url,
                            "mirror": mirror, "source": "Sci-Hub", "pdf_verified": True,
                            "status": "success", "diagnostics": diagnostics}
                except (requests.RequestException, ValueError) as exc:
                    candidate_errors.append(str(exc))
            diagnostics.append({"mirror": mirror, "status": "invalid_pdf" if candidates else status,
                                "errors": candidate_errors})
        except requests.exceptions.SSLError as exc:
            diagnostics.append({"mirror": mirror, "status": "tls_error", "error": str(exc)})
        except (requests.RequestException, ValueError) as exc:
            diagnostics.append({"mirror": mirror, "status": "network_error", "error": str(exc)})
    statuses = {entry["status"] for entry in diagnostics}
    status = "timeout" if "timeout" in statuses else "blocked" if "blocked" in statuses else "not_found" if statuses == {"not_found"} else "unavailable"
    return {"doi": doi, "pdf_url": "", "status": status, "diagnostics": diagnostics,
            "error": "No verified PDF link; inspect mirror diagnostics"}


def _metadata(item):
    authors = [" ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
               for a in (item.get("author") or [])]
    dates = item.get("published", item.get("issued", {})).get("date-parts", [[]])
    return {"doi": item.get("DOI", "").lower(), "title": "; ".join((item.get("title") or [])),
            "author": "; ".join(authors), "year": str(dates[0][0]) if dates and dates[0] else "",
            "journal": "; ".join((item.get("container-title") or []))}


def _crossref(session, deadline, doi=None, **params):
    url = "https://api.crossref.org/works" + ("/" + quote(doi, safe="") if doi else "")
    with _get(session, url, deadline, params=params) as response:
        response.raise_for_status()
        return response.json()["message"]


def get_metadata_by_doi(doi):
    try:
        doi = normalize_doi(doi)
        with create_session() as session:
            item = _crossref(session, time.monotonic() + 25, doi=doi)
        return {**_metadata(item), "pdf_url": next((link["URL"] for link in item.get("link", [])
                if link.get("content-type") == "application/pdf"), ""), "source": "Crossref", "status": "success"}
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.error("Metadata lookup failed: %s", exc)
        return {"doi": doi, "status": "error", "error": str(exc)}


def search_paper_by_doi(doi):
    try:
        doi = normalize_doi(doi)
        settings = load_settings()
        with create_session(settings) as session:
            return _resolve_doi(doi, session, settings["mirrors"], time.monotonic() + SEARCH_SECONDS)
    except (requests.RequestException, ValueError) as exc:
        logger.error("DOI search failed: %s", exc)
        return {"doi": doi, "pdf_url": "", "status": "error", "error": str(exc)}


def _title_key(title):
    return " ".join(re.findall(r"\w+", title.casefold()))


def search_paper_by_title(title, author=None, year=None, journal=None):
    deadline = time.monotonic() + SEARCH_SECONDS
    try:
        settings = load_settings()
        with create_session(settings) as session:
            items = _crossref(session, deadline, **{"query.title": title, "rows": 5}).get("items", [])
            ranked = []
            for item in items:
                metadata = _metadata(item)
                if metadata["doi"]:
                    if author and _title_key(author) not in _title_key(metadata["author"]):
                        continue
                    if year is not None and str(year) != metadata["year"]:
                        continue
                    if journal and _title_key(journal) not in _title_key(metadata["journal"]):
                        continue
                    score = SequenceMatcher(None, _title_key(title), _title_key(metadata["title"])).ratio()
                    ranked.append((score, metadata))
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            exact = [metadata for score, metadata in ranked if score == 1]
            if exact:
                candidates = exact
            elif ranked and ranked[0][0] >= 0.9 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.08):
                candidates = [ranked[0][1]]
            else:
                return {"status": "ambiguous" if ranked else "not_found", "query": title,
                        "candidates": [dict(metadata, title_match=round(score, 3)) for score, metadata in ranked],
                        "error": "Choose a DOI from the candidates to avoid retrieving the wrong paper"}
            publications = {(candidate["journal"].casefold(), candidate["year"], candidate["author"].casefold())
                            for candidate in candidates}
            if len(publications) > 1:
                return {"status": "ambiguous", "query": title, "candidates": candidates,
                        "error": "Multiple publications have this title; specify DOI or author/year/journal"}
            attempts = []
            for metadata in candidates:
                if time.monotonic() >= deadline:
                    break
                per_candidate = min(deadline, time.monotonic() + 35)
                result = _resolve_doi(metadata["doi"], session, settings["mirrors"], per_candidate)
                if result["status"] == "success":
                    result.update({key: value for key, value in metadata.items() if value})
                    result.update(query=title, matched_by="title", candidates=candidates, attempted_candidates=attempts)
                    if len(candidates) > 1:
                        result["version_note"] = "Multiple records have this title; the returned DOI/journal identifies the available version."
                    return result
                attempts.append({**metadata, **result})
            return {"status": "unavailable", "query": title, "candidates": candidates,
                    "attempted_candidates": attempts, "error": "No title candidate produced a verified PDF"}
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.error("Title search failed: %s", exc)
        return {"title": title, "status": "error", "error": str(exc)}


def search_papers_by_keyword(keyword, num_results=10):
    if not 1 <= num_results <= 20:
        return [{"status": "error", "error": "num_results must be between 1 and 20"}]
    deadline = time.monotonic() + SEARCH_SECONDS
    papers = []
    try:
        settings = load_settings()
        with create_session(settings) as session:
            rows = min(50, max(10, num_results * 3))
            items = _crossref(session, deadline, query=keyword, rows=rows).get("items", [])
            seen = set()
            for item in items:
                # Crossref also indexes grants and peer-review reports; search scholarly works.
                if not item.get("DOI") or item.get("type") in {"grant", "peer-review", "dataset"}:
                    continue
                metadata = _metadata(item)
                if metadata["doi"] in seen:
                    continue
                seen.add(metadata["doi"])
                if time.monotonic() >= deadline:
                    break
                result = _resolve_doi(metadata["doi"], session, settings["mirrors"],
                                      min(deadline, time.monotonic() + 20))
                papers.append({**result, **metadata})
                if sum(paper["status"] == "success" for paper in papers) >= num_results:
                    break
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.error("Keyword search failed: %s", exc)
        papers.append({"status": "error", "error": str(exc)})
    # Preserve relevance order within successful and unresolved groups.
    return sorted(papers, key=lambda paper: paper["status"] != "success")[:num_results]


def download_paper(pdf_url, output_path):
    """Download a validated PDF atomically, preserving existing files on failure."""
    target = Path(output_path)
    temporary = target.with_name(target.name + ".part")
    deadline = time.monotonic() + SEARCH_SECONDS
    created_temporary = False
    try:
        with create_session() as session:
            with _get(session, urldefrag(pdf_url)[0], deadline, stream=True) as response:
                response.raise_for_status()
                chunks = response.iter_content(chunk_size=65536)
                first = next(chunks, b"")
                if not first.startswith(b"%PDF-"):
                    raise ValueError("The response is not a PDF")
                with temporary.open("xb") as output:
                    created_temporary = True
                    output.write(first)
                    for chunk in chunks:
                        if time.monotonic() >= deadline:
                            raise requests.Timeout("Download time budget exhausted")
                        output.write(chunk)
                temporary.replace(target)
        return True
    except (requests.RequestException, ValueError, OSError) as exc:
        logger.error("Download failed: %s", exc)
        return False
    finally:
        if created_temporary and temporary.exists():
            temporary.unlink()