"""Verify the installed stdio server; add --online for real retrieval/download checks."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
DOI = "10.1371/journal.pmed.0020124"
EXPECTED_TOOLS = {
    "search_scihub_by_doi", "search_scihub_by_title", "search_scihub_by_keyword",
    "get_paper_metadata", "download_scihub_pdf",
}


def payload(reply):
    if reply.isError:
        raise RuntimeError(str(reply.content))
    data = reply.structuredContent
    if data is not None:
        return data.get("result", data)
    return [item.text for item in reply.content if item.type == "text"]


async def verify(args, report):
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                                      "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SCIHUB_MIRRORS"}}
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    parameters = StdioServerParameters(command=sys.executable,
        args=["-B", "-u", str(ROOT / "sci_hub_server.py")], cwd=str(ROOT), env=environment)

    async def call(session, name, arguments):
        print(f"Checking {name} ...", flush=True)
        started = time.monotonic()
        result = payload(await asyncio.wait_for(session.call_tool(name, arguments), timeout=180))
        report.setdefault("calls", []).append({"tool": name, "arguments": arguments,
            "seconds": round(time.monotonic() - started, 2), "result": result})
        return result

    with (directory / "mcp-stderr.log").open("w", encoding="utf-8") as log:
        async with stdio_client(parameters, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), timeout=30)
                tools = (await session.list_tools()).tools
                assert {tool.name for tool in tools} == EXPECTED_TOOLS, "Unexpected MCP tool catalog"
                assert all(tool.description for tool in tools), "Missing tool description"
                title_tool = next(tool for tool in tools if tool.name == "search_scihub_by_title")
                assert {"title", "author", "year", "journal"} <= set(title_tool.inputSchema["properties"])
                report["tools"] = sorted(EXPECTED_TOOLS)
                print("MCP startup and all five tool schemas passed.", flush=True)
                if not args.online:
                    return

                metadata = await call(session, "get_paper_metadata", {"doi": DOI})
                assert metadata.get("status") == "success" and metadata.get("doi") == DOI, "Crossref lookup failed"
                result = await call(session, "search_scihub_by_doi", {"doi": DOI})
                assert result.get("status") == "success" and result.get("pdf_verified"), "DOI lookup did not return a verified PDF"
                target = directory / "open-access-sample.pdf"
                download = await call(session, "download_scihub_pdf", {"pdf_url": result["pdf_url"], "output_path": str(target)})
                assert "PDF successfully downloaded" in str(download), "Download failed"
                content = target.read_bytes()
                assert content.startswith(b"%PDF-"), "Downloaded content is not a PDF"
                report["download"] = {"doi": DOI, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

                title = await call(session, "search_scihub_by_title", {"title": metadata["title"],
                    "year": int(metadata["year"]), "journal": metadata["journal"]})
                assert title.get("status") == "success" and title.get("doi") == DOI, "Title lookup failed or selected a different DOI"
                keywords = await call(session, "search_scihub_by_keyword", {"keyword": "published research findings false", "num_results": 3})
                count = sum(item.get("status") == "success" and bool(item.get("pdf_verified")) for item in keywords)
                assert count > 0, "Keyword search returned no verified PDF"
                report["keyword_verified_pdfs"] = count

        async with stdio_client(parameters, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), timeout=30)
                result = await call(session, "search_scihub_by_doi", {"doi": DOI})
                assert result.get("status") == "success" and result.get("pdf_verified"), "Lookup after server restart failed"
                report["restart_passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="Also query external sites and download an open-access sample")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "verification-output")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0], "online": args.online}
    try:
        asyncio.run(verify(args, report))
        report["passed"] = True
    except Exception as exc:
        report.update(passed=False, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Verification passed. Report: " + str(args.output_dir / "report.json"))


if __name__ == "__main__":
    main()
