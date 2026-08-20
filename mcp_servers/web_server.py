"""
ORION's web/internet MCP server — search and page-content retrieval.

Uses Tavily (official `tavily-python` SDK), which returns results
already cleaned up for LLM consumption rather than raw search-engine
HTML. Free tier: 1,000 searches/month, no card required.
Get a key at https://tavily.com and put it in .env as TAVILY_API_KEY.
"""

import os

from dotenv import load_dotenv
from fastmcp import FastMCP
from tavily import TavilyClient

load_dotenv()

API_KEY = os.environ.get("TAVILY_API_KEY")
if not API_KEY:
    raise RuntimeError("TAVILY_API_KEY not set — add it to .env (see .env.example)")

client = TavilyClient(api_key=API_KEY)

mcp = FastMCP(
    name="orion-web",
    instructions="Search the web and retrieve page content for current information the local model doesn't already know.",
)


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web. Returns a list of {title, url, snippet} results.

    The snippet is often enough to answer directly — only call
    web_fetch afterward if you need the full article text.
    """
    response = client.search(query, max_results=max_results)
    return [
        {"title": r["title"], "url": r["url"], "snippet": r["content"]}
        for r in response.get("results", [])
    ]


@mcp.tool()
def web_fetch(url: str) -> str:
    """Retrieve the full extracted text content of a specific webpage.

    Pass a specific article/page URL from web_search results — not a
    section front page or homepage listing (e.g. reuters.com/technology).
    Those return navigation and ad boilerplate instead of article text.
    """
    response = client.extract(url)
    results = response.get("results", [])
    if not results:
        raise ValueError(f"Could not extract content from {url}")
    # Verified against a live response: Tavily's extract puts the page
    # text in raw_content, not content — content came back empty/absent
    # on every page tested. Keep the content fallback in case that
    # changes for some page types.
    return results[0].get("raw_content") or results[0].get("content", "")


if __name__ == "__main__":
    mcp.run()
