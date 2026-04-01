from __future__ import annotations

"""Web-adapted Wikipedia contribution tracker for ClanDi 2.0.

Ported from wiki-tracker/wiki_tracker.py for use as a web module.
Fetches a single user's contributions from both EN and ES Wikipedia.
"""

import asyncio
from urllib.parse import quote

import httpx

WIKIS = ["en", "es"]

API_URLS = {
    "en": "https://en.wikipedia.org/w/api.php",
    "es": "https://es.wikipedia.org/w/api.php",
}

HEADERS = {
    "User-Agent": "ClanDi/2.0 (Wikipedia Editor Training; contact: wikibridge@example.com)",
}

ISSUE_KEYWORDS = {
    "Immigration": [
        "immigra", "deporta", "ICE ", "ice out", "border", "asylum", "refugee",
        "DACA", "undocumented", "detention", "visa", "citizenship", "migrant",
        "frontera", "sanctuary", "dreamers", "TPS", "CBP", "border patrol",
    ],
    "Economic Solidarity": [
        "econom", "labor", "wage", "worker", "union", "poverty",
        "inequality", "employ", "business", "entrepren", "income",
    ],
    "Midterms/Policy": [
        "election", "vote", "congress", "senator", "representative",
        "campaign", "ballot", "legislat", "policy", "governor",
        "political", "midterm",
    ],
    "Latino History & Culture": [
        "latin", "hispanic", "chicano", "boricua", "puerto ric",
        "cuban", "mexican", "dominican", "venezuelan", "colombian",
        "salsa", "reggaeton", "cumbia", "dia de los muertos",
        "nuyorican", "tejano", "afro-latin",
    ],
}


def classify_issue_area(title: str, comment: str = "") -> str:
    text = f"{title} {comment}".lower()
    for area, keywords in ISSUE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                return area
    return "Other"


def detect_contribution_type(edit: dict) -> str:
    if edit.get("parentid", 1) == 0:
        return "Created"
    tags = edit.get("tags", [])
    comment = edit.get("comment", "").lower()
    if "contenttranslation" in tags or "translat" in comment:
        return "Translated"
    return "Edited"


async def _fetch_contribs(
    client: httpx.AsyncClient,
    username: str,
    wiki: str,
) -> list[dict]:
    """Fetch recent mainspace contributions (last 6 months) for a user on one wiki."""
    api_url = API_URLS[wiki]
    all_contribs = []
    uccontinue = None

    while True:
        params = {
            "action": "query",
            "list": "usercontribs",
            "ucuser": username,
            "uclimit": "500",
            "ucprop": "title|timestamp|sizediff|comment|ids|tags",
            "ucnamespace": "0",
            "format": "json",
        }
        if uccontinue:
            params["uccontinue"] = uccontinue

        resp = await client.get(api_url, params=params, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        contribs = data.get("query", {}).get("usercontribs", [])
        for c in contribs:
            c["_wiki"] = wiki
        all_contribs.extend(contribs)

        uccontinue = data.get("continue", {}).get("uccontinue")
        if not uccontinue or len(all_contribs) >= 500:
            break

        await asyncio.sleep(0.05)

    return all_contribs


async def _fetch_pageviews(
    client: httpx.AsyncClient,
    title: str,
    wiki: str,
) -> int:
    """Fetch last-30-day pageviews for an article."""
    encoded = quote(title.replace(" ", "_"), safe="")
    from datetime import datetime, timedelta
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    url = (
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
        f"/{wiki}.wikipedia/all-access/user/{encoded}/daily/{start_str}/{end_str}"
    )
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            return sum(item.get("views", 0) for item in items)
    except Exception:
        pass
    return 0


async def fetch_user_contributions_web(username: str) -> list[dict]:
    """Fetch contributions for a user across EN and ES Wikipedia.

    Returns list of contribution dicts ready for database storage.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch from both wikis concurrently
        tasks = [_fetch_contribs(client, username, wiki) for wiki in WIKIS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_edits = []
        for result in results:
            if isinstance(result, list):
                all_edits.extend(result)

        if not all_edits:
            return []

        # Deduplicate by article — build per-article records
        article_map: dict[str, dict] = {}
        for edit in all_edits:
            wiki = edit["_wiki"]
            title = edit.get("title", "")
            key = f"{wiki}:{title}"

            contrib_type = detect_contribution_type(edit)
            issue_area = classify_issue_area(title, edit.get("comment", ""))

            if key not in article_map:
                article_map[key] = {
                    "article_title": title,
                    "wiki_lang": wiki,
                    "contribution_type": contrib_type,
                    "bytes_changed": max(0, edit.get("sizediff", 0)),
                    "edit_summary": edit.get("comment", ""),
                    "edit_timestamp": edit.get("timestamp", ""),
                    "pageviews_30d": 0,
                    "issue_area": issue_area,
                }
            else:
                rec = article_map[key]
                rec["bytes_changed"] += max(0, edit.get("sizediff", 0))
                # Upgrade type: Created > Translated > Edited
                if contrib_type == "Created":
                    rec["contribution_type"] = "Created"
                elif contrib_type == "Translated" and rec["contribution_type"] == "Edited":
                    rec["contribution_type"] = "Translated"
                # Keep most recent timestamp
                if edit.get("timestamp", "") > rec["edit_timestamp"]:
                    rec["edit_timestamp"] = edit["timestamp"]
                # Upgrade issue area from Other
                if rec["issue_area"] == "Other" and issue_area != "Other":
                    rec["issue_area"] = issue_area

        contributions = list(article_map.values())

        # Fetch pageviews for top articles (limit to 50 to stay fast)
        contributions.sort(key=lambda c: c["bytes_changed"], reverse=True)
        to_fetch = contributions[:50]

        pv_tasks = [
            _fetch_pageviews(client, c["article_title"], c["wiki_lang"])
            for c in to_fetch
        ]
        pv_results = await asyncio.gather(*pv_tasks, return_exceptions=True)
        for c, pv in zip(to_fetch, pv_results):
            if isinstance(pv, int):
                c["pageviews_30d"] = pv

    return contributions
