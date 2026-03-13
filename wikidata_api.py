"""Wikidata SPARQL client for finding cross-language knowledge gaps."""

import httpx

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "WikiBridge/1.0 (Knowledge Gap Tool; contact: wikibridge@example.com)",
    "Accept": "application/sparql-results+json",
}

# Find items by occupation/nationality/topic that exist in one wiki but not the other
# This uses Wikidata's structured properties for much better results
TOPIC_SEARCH_QUERY = """
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?article WHERE {{
  {{
    ?item ?prop ?topic .
    ?topic rdfs:label "{topic}"@en .
  }} UNION {{
    ?item ?prop ?topic .
    ?topic rdfs:label "{topic}"@es .
  }} UNION {{
    # Also match items whose label/description contains the search term
    ?item rdfs:label ?label .
    FILTER(LANG(?label) = "en")
    FILTER(CONTAINS(LCASE(?label), LCASE("{topic}")))
  }}
  {sitelink_filter}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{label_lang}" . }}
}}
LIMIT {limit}
"""

# Simpler, more reliable: search by Wikidata class/category
CATEGORY_QUERY = """
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?article WHERE {{
  ?item wdt:P31/wdt:P279* wd:{qid} .
  {sitelink_filter}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{label_lang}" . }}
}}
LIMIT {limit}
"""

# Direction-specific SPARQL fragments
DIRECTION_FILTERS = {
    "es_missing_en": {
        "sitelink_filter": """
  ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?article .
  FILTER NOT EXISTS {{
    ?eswiki schema:about ?item ; schema:isPartOf <https://es.wikipedia.org/> .
  }}""",
        "label_lang": "en,es",
    },
    "en_missing_es": {
        "sitelink_filter": """
  ?eswiki schema:about ?item ; schema:isPartOf <https://es.wikipedia.org/> ; schema:name ?article .
  FILTER NOT EXISTS {{
    ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
  }}""",
        "label_lang": "es,en",
    },
}


async def search_by_topic(
    topic: str, direction: str = "es_missing_en", limit: int = 100
) -> list[dict]:
    """Search for knowledge gaps by topic keyword using Wikidata SPARQL."""
    filters = DIRECTION_FILTERS[direction]
    safe_topic = topic.replace('"', '\\"').replace("\\", "\\\\")
    query = TOPIC_SEARCH_QUERY.format(
        topic=safe_topic,
        sitelink_filter=filters["sitelink_filter"],
        label_lang=filters["label_lang"],
        limit=limit,
    )
    return await _run_sparql(query)


async def search_by_category(
    qid: str, direction: str = "es_missing_en", limit: int = 200
) -> list[dict]:
    """Search for knowledge gaps by Wikidata category QID."""
    filters = DIRECTION_FILTERS[direction]
    query = CATEGORY_QUERY.format(
        qid=qid,
        sitelink_filter=filters["sitelink_filter"],
        label_lang=filters["label_lang"],
        limit=limit,
    )
    return await _run_sparql(query)


async def _run_sparql(query: str) -> list[dict]:
    """Execute a SPARQL query against Wikidata."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.get(
            SPARQL_ENDPOINT,
            params={"query": query, "format": "json"},
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    seen = set()
    for binding in data.get("results", {}).get("bindings", []):
        item_uri = binding.get("item", {}).get("value", "")
        qid = item_uri.split("/")[-1] if item_uri else ""
        if qid in seen:
            continue
        seen.add(qid)

        article_name = binding.get("article", {}).get("value", "")
        label = binding.get("itemLabel", {}).get("value", "")

        results.append(
            {
                "qid": qid,
                "label": label or article_name,
                "description": binding.get("itemDescription", {}).get("value", ""),
                "article": article_name,
                "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
            }
        )
    return results
