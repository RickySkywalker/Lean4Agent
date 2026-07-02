from __future__ import annotations

import asyncio
import json
import os
import re
import uuid

import aiofiles
from firecrawl import AsyncFirecrawl


async def firecrawl_search(query: str, num_results: int = 5) -> list:
    """
    Perform web search using FireCrawl API using the input query argument, and return the top results limited by num_results argument.

    Args:
        query: The search query string.
        num_results: Number of results to return (default is 5).

    Examples:
        firecrawl_search("Algorithmic improvements training techniques enhancing LLM mathematical reasoning GSM8K MATH", num_results=5)
        firecrawl_search("Enhancing LLM Reasoning via RLHF", num_results=10)

    Returns:
        A list of dictionaries containing searched content file path and the urls
    """

    def _sanitize_filename(name: str, max_len: int = 120) -> str:
        name = re.sub(r"[\\/:*?\"<>|\n\r\t-]", "_", name)
        name = re.sub(r"\s+", " ", name).strip()
        return (name[:max_len]).rstrip("._ ")

    FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
    firecrawl = AsyncFirecrawl(api_key=FIRECRAWL_API_KEY)

    max_retries = 3
    last_exc = None
    for attempt in range(max_retries):
        try:
            results = await firecrawl.search(
                query=query,
                limit=num_results,
                categories=["research"],
                scrape_options={
                    "formats": ["markdown"],
                    "parsers": ["pdf"],
                    "onlyMainContent": False,
                    "maxAge": 172800000,
                },
            )
            break
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (2**attempt))  # 0.5s, 1s, 2s
    else:
        raise last_exc

    json_str = (
        json.loads(results.model_dump_json())
        if hasattr(results, "model_dump_json")
        else results
    )

    final_result = []
    for item in json_str.get("web") or []:
        if "url" in item and item["url"]:
            final_url = item["url"]
        else:
            meta = item.get("metadata") or {}
            final_url = meta.get("sourceURL") or meta.get("url")

        title = (item.get("metadata") or {}).get("title") or final_url

        suffix = uuid.uuid4().hex[:6]
        file_name = f"{_sanitize_filename(title or 'result')}_{suffix}.md"
        file_name = file_name.replace(" ", "_")

        output_dir = os.path.join(
            os.environ.get("VM_WORKSPACE", "/workspace"), "browser", "url_downloads"
        )
        os.makedirs(output_dir, exist_ok=True)
        file_path = f"{output_dir}/{file_name}"

        try:
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(item["markdown"])

            final_result.append(
                {
                    "url": final_url,
                    "local_filename": file_path,
                }
            )
        except Exception as e:
            print(f"Failed to write {file_path}: {e}")
            continue

    return final_result
