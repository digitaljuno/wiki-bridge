# WikiBridge — Wikipedia Knowledge Gap Finder

Find Wikipedia articles that exist in English but are missing in Spanish (and vice versa). Built for the Maremoto/WikiLatinos program to prioritize translation and article creation work.

## Setup

```bash
cd wiki-bridge
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8000 in your browser.

## Features

### Topic Search
Search by keyword (e.g., "Mexican literature", "Colombian musicians"). Finds Wikipedia articles on that topic and checks which ones are missing in the other language.

### Category Search
Enter an exact Wikipedia category name (e.g., "Mexican novelists", "Latin American poets"). Fetches all articles in that category and shows coverage stats.

### Article List Check
Paste a list of article titles (one per line) and check which ones have translations. Shows coverage percentage and identifies gaps.

### Export
All results can be exported to CSV for sharing or importing into other tools.

## How It Works

- **Wikipedia Search API** — finds articles matching your topic
- **MediaWiki Langlinks API** — checks which articles have cross-language links
- **Wikipedia Category API** — fetches all members of a category
- **Wikidata SPARQL** — available for advanced category-based queries

## Sharing

To share with teammates, run the server on a machine accessible to others:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Or deploy to a free host like Render or Railway.
