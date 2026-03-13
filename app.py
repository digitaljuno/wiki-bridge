"""WikiBridge — Wikipedia Knowledge Gap Tool."""

import csv
import io

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import wikidata_api
import wikipedia_api

app = FastAPI(title="WikiBridge", description="Wikipedia EN↔ES Knowledge Gap Finder")
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
            "results": wiki_results,
        }
    except Exception as e:
        return {"error": str(e), "query": topic, "results": []}


@app.get("/api/category-search")
async def category_search(
    category: str = Query(..., description="Wikipedia category name"),
    direction: str = Query("es_missing_en", regex="^(es_missing_en|en_missing_es)$"),
    limit: int = Query(200, ge=1, le=500),
    deep: bool = Query(False, description="Include subcategories"),
):
    """Search by Wikipedia category — gets all articles in a category and checks gaps."""
    if direction == "es_missing_en":
        source_lang, target_lang = "en", "es"
    else:
        source_lang, target_lang = "es", "en"

    try:
        # Get category members (optionally with subcategories)
        if deep:
            titles = await wikipedia_api.get_category_members_recursive(
                category, source_lang, limit, max_depth=2
            )
        else:
            titles = await wikipedia_api.get_category_members(
                category, source_lang, limit
            )

        if not titles:
            return {
                "error": f"No articles found in category '{category}' on {source_lang}.wikipedia.org",
                "results": [],
            }

        # Check langlinks for all members
        results = await wikipedia_api.check_langlinks(
            titles, source_lang, target_lang
        )

        gaps = [r for r in results if r["exists_in_source"] and not r["has_translation"]]
        has_translation = [r for r in results if r["has_translation"]]
        stubs = [r for r in results if r.get("is_stub")]
        with_issues = [r for r in results if r.get("quality_issues")]

        return {
            "query": category,
            "direction": direction,
            "total_in_category": len(results),
            "total_gaps": len(gaps),
            "total_translated": len(has_translation),
            "coverage_pct": round(
                len(has_translation) / max(len(results), 1) * 100, 1
            ),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "query": category, "results": []}


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
        return {
            "total_checked": len(results),
            "total_missing": len(missing),
            "coverage_pct": round(
                (1 - len(missing) / max(len(results), 1)) * 100, 1
            ),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
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
        # Flatten list fields (quality_issues) for CSV
        for r in results:
            if isinstance(r.get("quality_issues"), list):
                r["quality_issues"] = "; ".join(r["quality_issues"])
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
