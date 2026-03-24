"""MediaWiki API client for checking interlanguage links and article quality."""

import asyncio
import re
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

STOPWORDS = {
    "in", "the", "of", "and", "a", "an", "to", "for", "on", "at", "by", "with",
    "is", "was", "are", "from", "or", "as", "its", "it", "be", "that", "this",
    # Spanish stopwords
    "de", "en", "la", "el", "los", "las", "del", "y", "por", "con", "una", "un",
    "para", "al", "es", "lo", "se", "su", "como", "que",
}


def _relevance_score(query: str, title: str) -> float:
    """Score how relevant a title is to the search query (0.0 to 1.0).
    Based on keyword overlap, ignoring stopwords."""
    query_words = {w for w in query.lower().split() if w not in STOPWORDS}
    if not query_words:
        return 1.0  # No meaningful keywords = accept everything
    title_lower = title.lower()
    matches = sum(1 for w in query_words if w in title_lower)
    return matches / len(query_words)


API_URLS = {
    "en": "https://en.wikipedia.org/w/api.php",
    "es": "https://es.wikipedia.org/w/api.php",
}

HEADERS = {
    "User-Agent": "WikiBridge/1.0 (Knowledge Gap Tool; contact: wikibridge@example.com)",
}


async def check_langlinks(
    titles: list[str],
    source_lang: str = "en",
    target_lang: str = "es",
    include_views: bool = True,
    include_target_quality: bool = True,
) -> list[dict]:
    """Check which articles from source_lang are missing in target_lang.
    Optionally enriches with pageviews and target-language quality data.

    Args:
        titles: List of article titles to check
        source_lang: Language code of the source Wikipedia (e.g., "en")
        target_lang: Language code to check for existence (e.g., "es")
        include_views: Fetch monthly pageviews per article
        include_target_quality: Check quality on translated articles too

    Returns:
        List of dicts with title, has_translation, quality, views info
    """
    if source_lang not in API_URLS:
        raise ValueError(f"Unsupported language: {source_lang}")

    api_url = API_URLS[source_lang]
    results = []

    # MediaWiki API allows up to 50 titles per request
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        batch_results = await _check_batch(api_url, batch, target_lang)
        results.extend(batch_results)

    # Enrich with target-language quality (stubs, sourcing, images on ES/EN side)
    if include_target_quality:
        results = await enrich_with_target_quality(results, target_lang)

    # Enrich with pageviews
    if include_views:
        results = await enrich_with_pageviews(results, source_lang)

    return results


def _parse_quality(page_data: dict) -> dict:
    """Extract quality signals (stub, sourcing, images) from a page query result."""
    # --- Categories: detect stubs via hidden categories ---
    categories = page_data.get("categories", [])
    is_stub = False
    stub_type = ""
    for cat in categories:
        cat_title = cat.get("title", "").lower()
        if "stub" in cat_title or "esbozo" in cat_title:
            is_stub = True
            stub_type = (
                cat.get("title", "")
                .replace("Category:", "")
                .replace("Categoría:", "")
            )
            break

    # --- Templates: detect sourcing issues ---
    templates = page_data.get("templates", [])
    quality_issues = []
    for tpl in templates:
        tpl_title = tpl.get("title", "").lower()
        if "citation needed" in tpl_title or "cita requerida" in tpl_title:
            quality_issues.append("Citation needed")
        elif "refimprove" in tpl_title or "more citations" in tpl_title:
            quality_issues.append("Needs more references")
        elif "unreferenced" in tpl_title or "sin referencias" in tpl_title:
            quality_issues.append("No references")
        elif "original research" in tpl_title:
            quality_issues.append("Original research")
        elif "pov" in tpl_title or "neutrality" in tpl_title:
            quality_issues.append("Neutrality disputed")
        elif "cleanup" in tpl_title or "wikificar" in tpl_title:
            quality_issues.append("Needs cleanup")
    quality_issues = list(dict.fromkeys(quality_issues))

    # --- Images: check if page has a main image ---
    has_image = page_data.get("thumbnail") is not None or page_data.get("pageimage") is not None

    return {
        "is_stub": is_stub,
        "stub_type": stub_type,
        "quality_issues": quality_issues,
        "has_image": has_image,
    }


async def _check_batch(
    api_url: str, titles: list[str], target_lang: str
) -> list[dict]:
    """Check a batch of up to 50 titles for langlinks, stub status, sourcing, and images."""
    params = {
        "action": "query",
        "prop": "langlinks|info|categories|templates|pageimages",
        "inprop": "url",
        "titles": "|".join(titles),
        "lllang": target_lang,
        "lllimit": "500",
        "clshow": "hidden",
        "cllimit": "500",
        "tllimit": "500",
        "tlnamespace": "10",
        "pithumbsize": "100",
        "format": "json",
        "origin": "*",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(api_url, params=params, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

    results = []
    pages = data.get("query", {}).get("pages", {})

    for page_id, page_data in pages.items():
        title = page_data.get("title", "")
        langlinks = page_data.get("langlinks", [])

        target_title = None
        for ll in langlinks:
            if ll.get("lang") == target_lang:
                target_title = ll.get("*", "")
                break

        missing = page_id == "-1" or page_data.get("missing") is not None
        quality = _parse_quality(page_data)
        source_url = page_data.get("fullurl", "")

        # Add "No image" to quality issues if missing
        if not missing and not quality["has_image"]:
            quality["quality_issues"].append("No image")

        results.append(
            {
                "title": title,
                "exists_in_source": not missing,
                "has_translation": target_title is not None,
                "target_title": target_title or "",
                "source_url": source_url,
                "is_stub": quality["is_stub"],
                "stub_type": quality["stub_type"],
                "quality_issues": quality["quality_issues"],
                "has_image": quality["has_image"],
                "source_bytes": page_data.get("length", 0) if not missing else 0,
                # Placeholders filled by enrich functions
                "monthly_views": 0,
                "target_quality": [],
                "target_is_stub": False,
                "target_bytes": 0,
                "depth_pct": 0,
            }
        )

    return results


async def _check_quality_batch(
    api_url: str, titles: list[str]
) -> dict[str, dict]:
    """Check quality (stubs, templates, images, length) for a batch of target-language articles.
    Returns a dict mapping title -> quality info."""
    if not titles:
        return {}

    params = {
        "action": "query",
        "prop": "categories|templates|pageimages|info",
        "titles": "|".join(titles),
        "clshow": "hidden",
        "cllimit": "500",
        "tllimit": "500",
        "tlnamespace": "10",
        "pithumbsize": "100",
        "format": "json",
        "origin": "*",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(api_url, params=params, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

    result = {}
    pages = data.get("query", {}).get("pages", {})
    for page_id, page_data in pages.items():
        if page_id == "-1" or page_data.get("missing") is not None:
            continue
        title = page_data.get("title", "")
        quality = _parse_quality(page_data)
        if not quality["has_image"]:
            quality["quality_issues"].append("No image")
        quality["length"] = page_data.get("length", 0)
        result[title] = quality
    return result


async def enrich_with_target_quality(
    results: list[dict], target_lang: str
) -> list[dict]:
    """For articles that have translations, check the target article's quality too."""
    if target_lang not in API_URLS:
        return results

    # Collect target titles that need checking
    target_titles = [
        r["target_title"] for r in results
        if r["has_translation"] and r["target_title"]
    ]
    if not target_titles:
        return results

    # Batch check target quality (50 at a time)
    target_quality = {}
    api_url = API_URLS[target_lang]
    for i in range(0, len(target_titles), 50):
        batch = target_titles[i : i + 50]
        batch_result = await _check_quality_batch(api_url, batch)
        target_quality.update(batch_result)

    # Merge target quality + length into results
    for r in results:
        if r["has_translation"] and r["target_title"] in target_quality:
            tq = target_quality[r["target_title"]]
            r["target_is_stub"] = tq["is_stub"]
            r["target_quality"] = tq["quality_issues"]
            r["target_bytes"] = tq.get("length", 0)

            # Compute depth ratio (target vs source)
            src = r.get("source_bytes", 0)
            tgt = r["target_bytes"]
            if src > 0:
                r["depth_pct"] = round(tgt / src * 100, 1)
            elif tgt > 0:
                r["depth_pct"] = 100.0
            else:
                r["depth_pct"] = 0

    return results


async def enrich_with_pageviews(
    results: list[dict], lang: str
) -> list[dict]:
    """Fetch monthly pageviews for articles and add to results.
    Uses the Wikimedia REST API (batches of 50 concurrent requests)."""
    # Date range: last 30 days
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    titles_to_check = [
        r["title"] for r in results if r["exists_in_source"]
    ]
    if not titles_to_check:
        return results

    async def fetch_views(client: httpx.AsyncClient, title: str) -> tuple[str, int]:
        encoded = quote(title.replace(" ", "_"), safe="")
        url = (
            f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
            f"/{lang}.wikipedia/all-access/user/{encoded}/daily/{start_str}/{end_str}"
        )
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                views = sum(item.get("views", 0) for item in items)
                return (title, views)
        except Exception:
            pass
        return (title, 0)

    # Fetch in batches of 50 concurrent requests to be polite
    views_map = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(titles_to_check), 50):
            batch = titles_to_check[i : i + 50]
            tasks = [fetch_views(client, t) for t in batch]
            batch_results = await asyncio.gather(*tasks)
            for title, views in batch_results:
                views_map[title] = views

    for r in results:
        r["monthly_views"] = views_map.get(r["title"], 0)

    return results


async def get_category_members(
    category: str, lang: str = "en", limit: int = 200
) -> list[str]:
    """Get article titles from a Wikipedia category.

    Args:
        category: Category name (with or without "Category:" prefix)
        lang: Language code
        limit: Max results

    Returns:
        List of article titles in the category
    """
    if lang not in API_URLS:
        raise ValueError(f"Unsupported language: {lang}")

    if not category.startswith("Category:") and not category.startswith("Categoría:"):
        category = f"Category:{category}"

    titles = []
    cmcontinue = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(titles) < limit:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": category,
                "cmtype": "page",
                "cmlimit": str(min(50, limit - len(titles))),
                "format": "json",
                "origin": "*",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue

            resp = await client.get(API_URLS[lang], params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

            members = data.get("query", {}).get("categorymembers", [])
            titles.extend(m["title"] for m in members)

            cmcontinue = data.get("continue", {}).get("cmcontinue")
            if not cmcontinue or not members:
                break

    return titles[:limit]


async def search_and_check_gaps(
    query: str,
    source_lang: str = "en",
    target_lang: str = "es",
    limit: int = 100,
) -> list[dict]:
    """Search Wikipedia for articles on a topic and check which are missing
    in the target language. Paginates through Wikipedia search results to get
    up to `limit` articles.

    Args:
        query: Search term
        source_lang: Language to search in
        target_lang: Language to check against
        limit: Max articles to check

    Returns:
        List of dicts with gap information
    """
    if source_lang not in API_URLS:
        raise ValueError(f"Unsupported language: {source_lang}")

    # Paginate through Wikipedia search results — fetch extra to allow
    # for filtering low-relevance results later
    raw_titles = []
    offset = 0
    page_size = 50  # Wikipedia API max per request
    fetch_limit = limit * 2  # Over-fetch so filtering doesn't leave us short

    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(raw_titles) < fetch_limit:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srnamespace": "0",
                "srlimit": str(min(page_size, fetch_limit - len(raw_titles))),
                "sroffset": str(offset),
                "srsort": "relevance",
                "format": "json",
                "origin": "*",
            }

            resp = await client.get(API_URLS[source_lang], params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

            search_results = data.get("query", {}).get("search", [])
            if not search_results:
                break

            raw_titles.extend(r["title"] for r in search_results)

            # Check if there are more results
            continue_data = data.get("continue", {})
            if "sroffset" not in continue_data:
                break
            offset = continue_data["sroffset"]

    if not raw_titles:
        return []

    # Filter by relevance — keep titles that share enough keywords with the query
    scored = [(t, _relevance_score(query, t)) for t in raw_titles]
    # Use a 0.4 threshold (at least 40% of query keywords must appear in title)
    threshold = 0.4
    filtered = [t for t, s in scored if s >= threshold]

    # If filtering removed too many, fall back to top results by score
    if len(filtered) < 10:
        scored.sort(key=lambda x: x[1], reverse=True)
        filtered = [t for t, _ in scored[:limit]]

    # Sort by relevance score (most relevant first) before passing to langlinks
    scored_filtered = [(t, _relevance_score(query, t)) for t in filtered]
    scored_filtered.sort(key=lambda x: x[1], reverse=True)
    titles = [t for t, _ in scored_filtered][:limit]

    # Check langlinks for all found titles
    return await check_langlinks(titles, source_lang, target_lang)


async def get_category_members_recursive(
    category: str, lang: str = "en", limit: int = 500, max_depth: int = 2
) -> list[str]:
    """Get article titles from a Wikipedia category and its subcategories.

    Args:
        category: Category name (with or without "Category:" prefix)
        lang: Language code
        limit: Max total results
        max_depth: How many levels of subcategories to crawl

    Returns:
        List of article titles
    """
    if lang not in API_URLS:
        raise ValueError(f"Unsupported language: {lang}")

    if not category.startswith("Category:") and not category.startswith("Categoría:"):
        category = f"Category:{category}"

    visited_cats = set()
    all_titles = []
    queue = [(category, 0)]  # (category_name, depth)

    async with httpx.AsyncClient(timeout=30.0) as client:
        while queue and len(all_titles) < limit:
            cat, depth = queue.pop(0)
            if cat in visited_cats:
                continue
            visited_cats.add(cat)

            cmcontinue = None
            while len(all_titles) < limit:
                params = {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": cat,
                    "cmtype": "page|subcat",
                    "cmlimit": "50",
                    "format": "json",
                    "origin": "*",
                }
                if cmcontinue:
                    params["cmcontinue"] = cmcontinue

                resp = await client.get(API_URLS[lang], params=params, headers=HEADERS)
                resp.raise_for_status()
                data = resp.json()

                members = data.get("query", {}).get("categorymembers", [])
                for m in members:
                    if m["ns"] == 0:  # Article namespace
                        if m["title"] not in all_titles:
                            all_titles.append(m["title"])
                    elif m["ns"] == 14 and depth < max_depth:  # Category namespace
                        queue.append((m["title"], depth + 1))

                cmcontinue = data.get("continue", {}).get("cmcontinue")
                if not cmcontinue or not members:
                    break

    return all_titles[:limit]


async def search_articles(query: str, lang: str = "en", limit: int = 10) -> list[str]:
    """Search Wikipedia for article titles matching a query.

    Args:
        query: Search string
        lang: Language code
        limit: Max results

    Returns:
        List of article titles
    """
    if lang not in API_URLS:
        raise ValueError(f"Unsupported language: {lang}")

    params = {
        "action": "opensearch",
        "search": query,
        "limit": str(limit),
        "namespace": "0",
        "format": "json",
        "origin": "*",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(API_URLS[lang], params=params, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

    # OpenSearch returns [query, [titles], [descriptions], [urls]]
    return data[1] if len(data) > 1 else []
