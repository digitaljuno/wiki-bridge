"""WikiBridge — Wikipedia Knowledge Gap Tool."""

import asyncio
import csv
import io
import json
import sys
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx

import wikidata_api
import wikipedia_api

sys.path.insert(0, str(Path(__file__).parent))
import wiki_wc_nav as wn

app = FastAPI(title="WikiBridge", description="Wikipedia EN↔ES Knowledge Gap Finder")


def _compute_priority(r: dict) -> int:
    """Compute a priority score for an article based on views, quality, and depth.
    Higher score = should be edited first."""
    import math

    score = 0
    views = r.get("monthly_views", 0)

    # Views give base priority (logarithmic scale so 100k views doesn't
    # completely dwarf everything else)
    if views > 0:
        score += int(math.log10(max(views, 1)) * 10)  # e.g. 10k views = 40pts

    # Missing translation is highest priority
    if not r.get("has_translation"):
        score += 50

    # Source quality issues
    if r.get("is_stub"):
        score += 30
    score += len(r.get("quality_issues", [])) * 10

    # Target quality issues (article exists but is bad)
    if r.get("target_is_stub"):
        score += 25
    score += len(r.get("target_quality", [])) * 10

    # Depth ratio penalty — translation exists but is thin
    depth = r.get("depth_pct", 0)
    if r.get("has_translation") and depth > 0:
        if depth < 20:
            score += 35  # Critically thin (< 20% of source)
        elif depth < 40:
            score += 25  # Very thin
        elif depth < 60:
            score += 15  # Thin

    return score
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/topic-search")
async def topic_search(
    topic: str = Query(..., min_length=1, description="Topic to search for"),
    direction: str = Query("es_missing_en", regex="^(es_missing_en|en_missing_es)$"),
    limit: int = Query(100, ge=1, le=500),
):
    """Search for knowledge gaps by topic.

    Uses Wikipedia search API + langlink checking as the primary strategy.
    Falls back to Wikidata SPARQL for broader coverage.
    """
    # Determine source/target languages from direction
    if direction == "es_missing_en":
        source_lang, target_lang = "en", "es"
    else:
        source_lang, target_lang = "es", "en"

    try:
        # Use Wikipedia search API + langlinks (fast, reliable, paginated)
        wiki_results = await wikipedia_api.search_and_check_gaps(
            topic, source_lang, target_lang, limit
        )

        # Separate gaps from translated
        gaps = [r for r in wiki_results if r["exists_in_source"] and not r["has_translation"]]
        translated = [r for r in wiki_results if r["has_translation"]]
        total_valid = len(gaps) + len(translated)

        # Quality stats
        stubs = [r for r in wiki_results if r.get("is_stub")]
        with_issues = [r for r in wiki_results if r.get("quality_issues")]
        target_issues = [r for r in wiki_results if r.get("target_quality") or r.get("target_is_stub")]

        # Compute priority score and sort by it
        for r in wiki_results:
            r["priority"] = _compute_priority(r)
        wiki_results.sort(key=lambda r: r["priority"], reverse=True)

        return {
            "query": topic,
            "direction": direction,
            "total_searched": len(wiki_results),
            "total_gaps": len(gaps),
            "total_translated": len(translated),
            "coverage_pct": round(
                len(translated) / max(total_valid, 1) * 100, 1
            ),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "total_target_issues": len(target_issues),
            "results": wiki_results,
        }
    except Exception as e:
        return {"error": str(e), "query": topic, "results": []}


@app.get("/api/category-search")
async def category_search(
    category: str = Query(None, description="Wikipedia category name (single, legacy)"),
    categories: str = Query(None, description="Pipe-separated category names (multi)"),
    direction: str = Query("es_missing_en", regex="^(es_missing_en|en_missing_es)$"),
    limit: int = Query(200, ge=1, le=500),
    deep: bool = Query(False, description="Include subcategories"),
):
    """Search by Wikipedia category. Accepts a single `category` or pipe-separated `categories`.

    When multiple categories are provided, articles are fetched from each in
    parallel, deduplicated by title, then checked for cross-language gaps.
    """
    import asyncio

    if direction == "es_missing_en":
        source_lang, target_lang = "en", "es"
    else:
        source_lang, target_lang = "es", "en"

    # Normalize input — support both `category` (single) and `categories` (pipe-separated)
    cat_list: list[str] = []
    if categories:
        cat_list = [c.strip() for c in categories.split("|") if c.strip()]
    elif category:
        cat_list = [category.strip()] if category.strip() else []

    if not cat_list:
        return {"error": "No categories provided", "results": []}

    try:
        # Fetch all categories in parallel
        async def _fetch(cat: str) -> tuple[str, list[str]]:
            if deep:
                titles = await wikipedia_api.get_category_members_recursive(
                    cat, source_lang, limit, max_depth=2
                )
            else:
                titles = await wikipedia_api.get_category_members(
                    cat, source_lang, limit
                )
            return cat, titles

        fetched = await asyncio.gather(*[_fetch(c) for c in cat_list])

        # Dedupe titles across categories, but track which categories each came from
        title_to_categories: dict[str, list[str]] = {}
        for cat_name, titles in fetched:
            for t in titles:
                title_to_categories.setdefault(t, []).append(cat_name)

        all_titles = list(title_to_categories.keys())

        if not all_titles:
            return {
                "error": f"No articles found in {'these categories' if len(cat_list) > 1 else f'category {cat_list[0]!r}'} on {source_lang}.wikipedia.org",
                "results": [],
            }

        # Check langlinks for all unique members
        results = await wikipedia_api.check_langlinks(
            all_titles, source_lang, target_lang
        )

        # Tag each result with the source categories it came from
        for r in results:
            r["source_categories"] = title_to_categories.get(r["title"], [])

        gaps = [r for r in results if r["exists_in_source"] and not r["has_translation"]]
        has_translation = [r for r in results if r["has_translation"]]
        stubs = [r for r in results if r.get("is_stub")]
        with_issues = [r for r in results if r.get("quality_issues")]
        target_issues = [r for r in results if r.get("target_quality") or r.get("target_is_stub")]

        for r in results:
            r["priority"] = _compute_priority(r)
        results.sort(key=lambda r: r["priority"], reverse=True)

        # Per-category counts for the summary
        per_category = []
        for cat_name, titles in fetched:
            per_category.append({"name": cat_name, "count": len(titles)})

        return {
            "query": " + ".join(cat_list),
            "categories": cat_list,
            "per_category": per_category,
            "direction": direction,
            "total_in_category": len(results),
            "total_gaps": len(gaps),
            "total_translated": len(has_translation),
            "coverage_pct": round(
                len(has_translation) / max(len(results), 1) * 100, 1
            ),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "total_target_issues": len(target_issues),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "query": " + ".join(cat_list), "results": []}


@app.get("/api/check-articles")
async def check_articles(
    titles: str = Query(..., description="Pipe-separated article titles"),
    source_lang: str = Query("en", regex="^(en|es)$"),
    target_lang: str = Query("es", regex="^(en|es)$"),
):
    """Check a list of articles for cross-language availability."""
    title_list = [t.strip() for t in titles.split("|") if t.strip()]
    if not title_list:
        return {"error": "No titles provided", "results": []}

    try:
        results = await wikipedia_api.check_langlinks(
            title_list, source_lang, target_lang
        )
        missing = [r for r in results if r["exists_in_source"] and not r["has_translation"]]
        stubs = [r for r in results if r.get("is_stub")]
        with_issues = [r for r in results if r.get("quality_issues")]
        target_issues = [r for r in results if r.get("target_quality") or r.get("target_is_stub")]

        for r in results:
            r["priority"] = _compute_priority(r)
        results.sort(key=lambda r: r["priority"], reverse=True)

        return {
            "total_checked": len(results),
            "total_missing": len(missing),
            "coverage_pct": round(
                (1 - len(missing) / max(len(results), 1)) * 100, 1
            ),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "total_target_issues": len(target_issues),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "results": []}


@app.get("/api/export-csv")
async def export_csv(
    data_json: str = Query(..., description="JSON array of results to export"),
):
    """Export results as CSV."""
    import json

    try:
        results = json.loads(data_json)
    except json.JSONDecodeError:
        results = []

    output = io.StringIO()
    if results:
        # Flatten list fields for CSV
        for r in results:
            if isinstance(r.get("quality_issues"), list):
                r["quality_issues"] = "; ".join(r["quality_issues"])
            if isinstance(r.get("target_quality"), list):
                r["target_quality"] = "; ".join(r["target_quality"])
        fieldnames = list(results[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="wikibridge-export.csv"'},
    )


@app.get("/api/article-paths")
async def article_paths(
    title: str = Query(..., min_length=1),
    lang: str = Query("en"),
    month: str = Query(""),
    cache_dir: str = Query("~/.cache/wiki-wc-nav"),
    limit: int = Query(25, ge=5, le=50),
):
    """Stream navigation paths for a single article as Server-Sent Events."""

    async def generate():
        def evt(type_: str, **kwargs) -> str:
            return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"

        try:
            cache_path = Path(cache_dir).expanduser()
            title_underscored = title.strip().replace(" ", "_")
            lang_code = lang.strip().lower()

            yield evt("progress", msg=f"Looking up paths for '{title}' on {lang_code.upper()} Wikipedia...")

            async with httpx.AsyncClient(timeout=120.0) as client:
                yield evt("progress", msg="Checking latest available clickstream month...")
                try:
                    year, month_num = await wn.resolve_clickstream_month(
                        client, forced=month or None
                    )
                    yield evt("progress", msg=f"Using: {year:04d}-{month_num:02d}")
                except Exception as e:
                    yield evt("error", msg=str(e))
                    return

                try:
                    path = await wn.download_clickstream(client, lang_code, year, month_num, cache_path)
                except Exception as e:
                    yield evt("error", msg=f"Download failed: {e}")
                    return

            yield evt("progress", msg=f"Scanning clickstream for '{title}' (may take 1–3 min for EN)...")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, wn.lookup_article_nav, path, title_underscored, limit
            )

            if not result["incoming"] and not result["outgoing"] and not result["external"]:
                yield evt("error", msg=f"No navigation data found for '{title}'. Check the spelling or try a different article.")
                return

            yield evt("done", **result, lang=lang_code, month=f"{year:04d}-{month_num:02d}")

        except Exception as e:
            yield evt("error", msg=f"Lookup failed: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/suggest")
async def suggest(q: str = Query(""), lang: str = Query("en")):
    """Wikipedia title autocomplete via MediaWiki search API."""
    if not q.strip():
        return {"results": []}
    api = wn.API_URLS.get(lang, wn.API_URLS["en"])
    params = {
        "action": "opensearch",
        "search": q,
        "limit": "8",
        "namespace": "0",
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(api, params=params, headers=wn.HEADERS)
            data = resp.json()
            return {"results": data[1] if len(data) > 1 else []}
    except Exception:
        return {"results": []}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
