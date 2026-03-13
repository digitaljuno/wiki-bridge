"""MediaWiki API client for checking interlanguage links and article quality."""

import re

import httpx

API_URLS = {
    "en": "https://en.wikipedia.org/w/api.php",
    "es": "https://es.wikipedia.org/w/api.php",
}

HEADERS = {
    "User-Agent": "WikiBridge/1.0 (Knowledge Gap Tool; contact: wikibridge@example.com)",
}


async def check_langlinks(
    titles: list[str], source_lang: str = "en", target_lang: str = "es"
) -> list[dict]:
    """Check which articles from source_lang are missing in target_lang.

    Args:
        titles: List of article titles to check
        source_lang: Language code of the source Wikipedia (e.g., "en")
        target_lang: Language code to check for existence (e.g., "es")

    Returns:
        List of dicts with title, has_translation, target_title info
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

    return results


async def _check_batch(
    api_url: str, titles: list[str], target_lang: str
) -> list[dict]:
    """Check a batch of up to 50 titles for langlinks, stub status, and sourcing quality."""
    params = {
        "action": "query",
        "prop": "langlinks|info|categories|templates",
        "inprop": "url",
        "titles": "|".join(titles),
        "lllang": target_lang,
        "lllimit": "500",
        # Hidden categories include stub markers
        "clshow": "hidden",
        "cllimit": "500",
        # Templates — limit to 500 to catch maintenance banners
        "tllimit": "500",
        "tlnamespace": "10",
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

        # --- Langlinks: find target language translation ---
        target_title = None
        for ll in langlinks:
            if ll.get("lang") == target_lang:
                target_title = ll.get("*", "")
                break

        missing = page_id == "-1" or page_data.get("missing") is not None

        # --- Categories: detect stubs via hidden categories ---
        categories = page_data.get("categories", [])
        is_stub = False
        stub_type = ""
        for cat in categories:
            cat_title = cat.get("title", "").lower()
            if "stub" in cat_title or "esbozo" in cat_title:
                is_stub = True
                # Extract a readable stub type from "Category:Mexican writer stubs"
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
        # Deduplicate
        quality_issues = list(dict.fromkeys(quality_issues))

        source_url = page_data.get("fullurl", "")
        results.append(
            {
                "title": title,
                "exists_in_source": not missing,
                "has_translation": target_title is not None,
                "target_title": target_title or "",
                "source_url": source_url,
                "is_stub": is_stub,
                "stub_type": stub_type,
                "quality_issues": quality_issues,
            }
        )

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

    # Paginate through Wikipedia search results
    titles = []
    offset = 0
    page_size = 50  # Wikipedia API max per request

    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(titles) < limit:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srnamespace": "0",
                "srlimit": str(min(page_size, limit - len(titles))),
                "sroffset": str(offset),
                "format": "json",
                "origin": "*",
            }

            resp = await client.get(API_URLS[source_lang], params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

            search_results = data.get("query", {}).get("search", [])
            if not search_results:
                break

            titles.extend(r["title"] for r in search_results)

            # Check if there are more results
            continue_data = data.get("continue", {})
            if "sroffset" not in continue_data:
                break
            offset = continue_data["sroffset"]

    if not titles:
        return []

    # Check langlinks for all found titles
    return await check_langlinks(titles[:limit], source_lang, target_lang)


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
