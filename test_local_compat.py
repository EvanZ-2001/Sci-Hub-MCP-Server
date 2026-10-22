import ast
import contextlib
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
import sci_hub_search as search

ROOT = Path(__file__).resolve().parent
DOI = "10.1371/journal.pone.0000308"
PDF = b"%PDF-1.4\nfixture PDF\n"


def response(body=b"", url="https://mirror.test/paper", status=200):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.encoding = "utf-8"
    result._content = body.encode() if isinstance(body, str) else body
    result._content_consumed = True
    return result


class SearchRepairTests(unittest.TestCase):
    def test_fresh_install_has_fallback_mirrors_and_no_private_proxy(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            with patch.object(search, "SETTINGS_PATH", Path(folder) / "missing.json"), patch.dict(search.os.environ, {}, clear=True):
                settings = search.load_settings()
        self.assertGreaterEqual(len(settings["mirrors"]), 2)
        self.assertTrue(all(url.startswith("https://") for url in settings["mirrors"]))
        self.assertFalse(settings.get("proxy"))

    def test_mirror_environment_is_used_without_local_settings(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            with patch.object(search, "SETTINGS_PATH", Path(folder) / "missing.json"), patch.dict(search.os.environ, {"SCIHUB_MIRRORS": "one.test/,https://two.test"}, clear=True):
                self.assertEqual(search.load_settings()["mirrors"], ["https://one.test", "https://two.test"])

    def test_local_settings_override_mirror_environment(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "settings.local.json"
            path.write_text('{"mirrors":["local.test"],"proxy":"http://127.0.0.1:1234"}', encoding="utf-8")
            with patch.object(search, "SETTINGS_PATH", path), patch.dict(search.os.environ, {"SCIHUB_MIRRORS": "env.test"}, clear=True):
                settings = search.load_settings()
            self.assertEqual(settings["mirrors"], ["https://local.test"])
            self.assertEqual(settings["proxy"], "http://127.0.0.1:1234")

    def test_current_object_and_relative_url(self):
        links, metadata, status = search.parse_article(
            '<meta name="citation_title" content="Paper"><object data="/storage/p.pdf#view=FitH"></object>',
            "https://mirror.test/10.1234/paper")
        self.assertEqual(links, ["https://mirror.test/storage/p.pdf"])
        self.assertEqual(metadata["title"], "Paper")

    def test_all_supported_pdf_markers_and_deduplication(self):
        html = '''<meta name="citation_pdf_url" content="//cdn.test/p.pdf">
        <iframe src="../p.pdf#view=FitH"></iframe><embed src="../p.pdf">
        <a href="https://mirror.test/about">About</a><a href="/file?id=1" download>Download</a>
        <button onclick="location.href='/button.pdf'">Save</button>
        <object data="javascript:alert(1)"></object>'''
        links, _, _ = search.parse_article(html, "https://mirror.test/article/doi")
        self.assertEqual(links, ["https://cdn.test/p.pdf", "https://mirror.test/p.pdf", "https://mirror.test/file?id=1", "https://mirror.test/button.pdf"])

    def test_challenge_detection_does_not_reject_normal_article(self):
        self.assertEqual(search.parse_article('<title>Sci-Hub: проверка на робота</title>', "https://mirror.test")[2], "blocked")
        self.assertEqual(search.parse_article('<title>Just a moment...</title>', "https://mirror.test")[2], "blocked")
        self.assertNotEqual(search.parse_article('<title>Sci-Hub Paper</title><object data="/p.pdf"></object><p>verify you are human</p>', "https://mirror.test")[2], "blocked")

    def test_doi_url_and_invalid_input(self):
        self.assertEqual(search.normalize_doi("https://doi.org/" + DOI.upper()), DOI)
        with self.assertRaises(ValueError):
            search.normalize_doi("not a doi")

    def test_pdf_content_required_even_with_pdf_mime_type(self):
        session = MagicMock()
        html = response("<html>blocked</html>")
        html.headers["Content-Type"] = "application/pdf"
        session.get.return_value = html
        with self.assertRaises(ValueError):
            search.validate_pdf(session, "https://mirror.test/p.pdf", "https://mirror.test", time.monotonic() + 10)
        self.assertIs(session.get.call_args.kwargs["verify"], True)
        self.assertTrue(session.get.call_args.kwargs["stream"])

    def test_probe_reads_only_prefix_and_returns_final_url(self):
        session = MagicMock()
        session.get.return_value = response(PDF + b"x" * 5000, url="https://cdn.test/p.pdf")
        result = search.validate_pdf(session, "https://mirror.test/p.pdf", "https://mirror.test", time.monotonic() + 10)
        self.assertEqual(result, "https://cdn.test/p.pdf")
        self.assertEqual(session.get.call_args.kwargs["headers"]["Range"], "bytes=0-1023")

    def test_deadline_exhaustion_makes_no_network_request(self):
        session = MagicMock()
        with self.assertRaises(requests.Timeout):
            search._get(session, "https://mirror.test", time.monotonic() - 1)
        session.get.assert_not_called()

    def test_fallback_after_challenge_and_invalid_first_pdf_candidate(self):
        session = MagicMock()
        session.get.side_effect = [response('<title>DDoS-Guard</title>', status=403),
            response('<iframe src="/not.pdf"></iframe><object data="/yes.pdf"></object>', url="https://second.test/paper"),
            response(PDF, url="https://second.test/yes.pdf")]
        result = search._resolve_doi(DOI, session, ["https://first.test", "https://second.test"], time.monotonic() + 10)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["diagnostics"][0]["status"], "blocked")
        self.assertEqual(result["pdf_url"], "https://second.test/yes.pdf")

    def test_invalid_candidate_does_not_hide_second_valid_candidate(self):
        session = MagicMock()
        session.get.side_effect = [response('<object data="/bad.pdf"></object><object data="/good.pdf"></object>'), response('<html>Error</html>'), response(PDF, url="https://mirror.test/good.pdf")]
        result = search._resolve_doi(DOI, session, ["https://mirror.test"], time.monotonic() + 10)
        self.assertEqual(result["pdf_url"], "https://mirror.test/good.pdf")

    def test_page_with_wrong_doi_is_rejected(self):
        session = MagicMock()
        session.get.return_value = response('<meta name="citation_doi" content="10.0000/wrong"><object data="/p.pdf"></object>')
        result = search._resolve_doi(DOI, session, ["https://mirror.test"], time.monotonic() + 10)
        self.assertNotEqual(result["status"], "success")
        self.assertEqual(result["diagnostics"][0]["status"], "doi_mismatch")

    def test_title_uses_journal_to_select_third_candidate(self):
        items = [{"DOI": "10.0000/" + str(i), "title": ["Exact paper title"], "container-title": [str(i)]} for i in range(3)]
        with patch.object(search, "create_session") as factory, patch.object(search, "_crossref", return_value={"items": items}) as crossref, patch.object(search, "_resolve_doi") as resolve:
            factory.return_value.__enter__.return_value = MagicMock()
            resolve.return_value = {"status": "success", "pdf_url": "https://mirror.test/p.pdf"}
            result = search.search_paper_by_title("Exact paper title", journal="2")
        self.assertEqual(result["doi"], "10.0000/2")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(crossref.call_args.kwargs["rows"], 5)

    def test_same_title_different_publications_requires_selection(self):
        items = [{"DOI": "10.0000/" + str(i), "title": ["Same title"], "container-title": [str(i)]} for i in range(2)]
        with patch.object(search, "create_session"), patch.object(search, "_crossref", return_value={"items": items}), patch.object(search, "_resolve_doi") as resolve:
            result = search.search_paper_by_title("Same title")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)
        resolve.assert_not_called()

    def test_keyword_checks_beyond_requested_count_for_pdf_links(self):
        items = [{"DOI": "10.0000/" + str(i), "title": [str(i)]} for i in range(5)]
        results = [{"status": "not_found"}] * 4 + [{"status": "success", "pdf_url": "https://m.test/p.pdf"}]
        with patch.object(search, "create_session"), patch.object(search, "_crossref", return_value={"items": items}) as crossref, patch.object(search, "_resolve_doi", side_effect=results):
            result = search.search_papers_by_keyword("test", 1)
        self.assertEqual(result[0]["doi"], "10.0000/4")
        self.assertEqual(result[0]["status"], "success")
        self.assertEqual(crossref.call_args.kwargs["rows"], 10)

    def test_metadata_handles_null_crossref_fields(self):
        result = search._metadata({"DOI": DOI, "title": None, "author": None, "container-title": None})
        self.assertEqual(result["title"], "")

    def test_ambiguous_title_returns_candidates_without_pdf_lookup(self):
        items = [{"DOI": DOI, "title": ["Completely different title"]}]
        with patch.object(search, "create_session"), patch.object(search, "_crossref", return_value={"items": items}), patch.object(search, "_resolve_doi") as resolve:
            result = search.search_paper_by_title("Unknown query")
        self.assertEqual(result["status"], "ambiguous")
        resolve.assert_not_called()

    def test_keyword_preserves_metadata_on_failure_and_bounds_rows(self):
        items = [{"DOI": DOI, "title": ["Paper"], "author": [{"family": "Smith"}]}]
        with patch.object(search, "create_session"), patch.object(search, "_crossref", return_value={"items": items}), patch.object(search, "_resolve_doi", return_value={"status": "blocked", "pdf_url": ""}):
            result = search.search_papers_by_keyword("data sharing", 1)
        self.assertEqual(result[0]["title"], "Paper")
        self.assertEqual(result[0]["status"], "blocked")
        self.assertEqual(search.search_papers_by_keyword("test", 100)[0]["status"], "error")

    def test_metadata_is_independent_of_scihub(self):
        item = {"DOI": DOI, "title": ["Paper"], "author": [{"given": "Ada", "family": "Lovelace"}], "published": {"date-parts": [[2020]]}}
        with patch.object(search, "create_session"), patch.object(search, "_crossref", return_value=item), patch.object(search, "_resolve_doi") as resolve:
            result = search.get_metadata_by_doi(DOI)
        self.assertEqual(result["author"], "Ada Lovelace")
        self.assertEqual(result["year"], "2020")
        self.assertEqual(result["source"], "Crossref")
        resolve.assert_not_called()

    def test_crossref_passes_query_parameters_separately(self):
        session = MagicMock()
        session.get.return_value = response('{"message":{"items":[]}}')
        search._crossref(session, time.monotonic() + 10, **{"query.title": "A & B", "rows": 5})
        self.assertEqual(session.get.call_args.kwargs["params"], {"query.title": "A & B", "rows": 5})

    def test_network_errors_do_not_pollute_stdout(self):
        with patch.object(search, "create_session"), patch.object(search, "_resolve_doi", side_effect=requests.Timeout("test")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = search.search_paper_by_doi(DOI)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(result["status"], "error")

    def test_project_proxy_works_without_environment(self):
        with patch.dict(search.os.environ, {}, clear=True):
            with search.create_session({"proxy": "http://127.0.0.1:1234"}) as session:
                self.assertEqual(session.proxies["https"], "http://127.0.0.1:1234")
                self.assertFalse(session.trust_env)
                self.assertTrue(session.verify)

    def test_download_rejects_html_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            target = Path(folder) / "paper.pdf"
            target.write_bytes(b"original")
            with patch.object(search, "_get", return_value=response("<html>blocked</html>")):
                self.assertFalse(search.download_paper("https://mirror.test/p.pdf", target))
            self.assertEqual(target.read_bytes(), b"original")
            self.assertFalse(target.with_name("paper.pdf.part").exists())

    def test_pdf_download_and_cleanup_after_interruption(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            target = Path(folder) / "paper.pdf"
            with patch.object(search, "_get", return_value=response(PDF)):
                self.assertTrue(search.download_paper("https://mirror.test/p.pdf", target))
            self.assertEqual(target.read_bytes(), PDF)
            def broken():
                yield PDF
                raise requests.Timeout("broken transfer")
            result = response(PDF)
            result.iter_content = MagicMock(return_value=broken())
            with patch.object(search, "_get", return_value=result):
                self.assertFalse(search.download_paper("https://mirror.test/p.pdf", target))
            self.assertEqual(target.read_bytes(), PDF)
            self.assertFalse(target.with_name("paper.pdf.part").exists())

    def test_all_five_mcp_tools_have_descriptions(self):
        tree = ast.parse((ROOT / "sci_hub_server.py").read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
        self.assertEqual(len(functions), 5)
        for function in functions:
            self.assertTrue(ast.get_docstring(function), function.name)


if __name__ == "__main__":
    unittest.main()