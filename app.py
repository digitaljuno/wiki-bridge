from __future__ import annotations

"""ClanDi 2.0 — Wikipedia Editor Training & Impact Platform.

Expands WikiBridge into a full training, tracking, and gamification app.
"""

import csv
import httpx
import io
import math
import os
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not required in production

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import auth
import database as db
import discord_webhook
import gamification
import tracker
import wikidata_api
import wikipedia_api

app = FastAPI(title="ClanDi", description="Wikipedia Editor Training & Impact Platform")

# Session middleware for auth
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_urlsafe(32))
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Badge emoji map for templates
BADGE_ICONS = {
    "first_login": "&#x1F43E;",     # paw prints
    "training_complete": "&#x1F393;", # graduation cap
    "first_edit": "&#x270F;",        # pencil
    "puente": "&#x1F309;",           # bridge
    "sourcing_pro": "&#x1F4DA;",     # books
    "gap_closer": "&#x1F3AF;",       # target
    "momentum_3": "&#x1F525;",       # flame
    "community_builder": "&#x1F91D;", # handshake
    "module_1": "&#x1F9ED;",         # compass
    "module_3": "&#x1F528;",         # hammer
}


# ---- Helpers ----

def _get_user(request: Request) -> dict | None:
    """Get current user from session."""
    user_id = request.session.get("user_id")
    if user_id:
        return db.get_user_by_id(user_id)
    return None


def _format_views(views: int) -> str:
    """Format pageview numbers for display."""
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    elif views >= 1_000:
        return f"{views / 1_000:.1f}K"
    return str(views)


def _community_stats_display() -> dict:
    """Get community stats with formatted display values."""
    stats = db.get_community_stats()
    stats["total_views_display"] = _format_views(stats["total_views"])
    return stats


def _compute_priority(r: dict) -> int:
    """Compute a priority score for an article based on views, quality, and depth."""
    score = 0
    views = r.get("monthly_views", 0)
    if views > 0:
        score += int(math.log10(max(views, 1)) * 10)
    if not r.get("has_translation"):
        score += 50
    if r.get("is_stub"):
        score += 30
    score += len(r.get("quality_issues", [])) * 10
    if r.get("target_is_stub"):
        score += 25
    score += len(r.get("target_quality", [])) * 10
    depth = r.get("depth_pct", 0)
    if r.get("has_translation") and depth > 0:
        if depth < 20:
            score += 35
        elif depth < 40:
            score += 25
        elif depth < 60:
            score += 15
    return score



# ========== Page Routes ==========

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    user = _get_user(request)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    stats = _community_stats_display()
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "user": None,
        "active": "home",
        "lang": "en",
        "stats": stats,
        "oauth_configured": auth.is_configured(),
    })


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    completed_modules = db.get_training_progress(user["id"])
    badges = db.get_user_badges(user["id"])
    community = _community_stats_display()
    momentum_weeks = db.get_momentum_weeks(user["id"])
    consecutive_weeks = db.get_consecutive_weeks(user["id"])

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "active": "dashboard",
        "lang": user.get("language_pref", "en"),
        "completed_modules": completed_modules,
        "badges": badges,
        "badge_icons": BADGE_ICONS,
        "community": community,
        "momentum_weeks": momentum_weeks,
        "consecutive_weeks": consecutive_weeks,
    })


@app.get("/training", response_class=HTMLResponse)
async def training(request: Request):
    """Journey tracker page — overview of all 6 modules with progress states."""
    user = _get_user(request)
    if user:
        state = db.get_training_state(user["id"])
    else:
        # Build empty state
        state = {
            "modules": [{
                "module_id": mid,
                "section_index": 1,
                "total_sections": db.MODULE_TOTAL_SECTIONS[mid],
                "completed": False,
                "completed_at": None,
                "updated_at": None,
                "checks_passed": 0,
                "checks_total": 0,
                "tasks_completed": 0,
                "tasks_total": 0,
            } for mid in range(1, 7)],
            "stats": {
                "modules_completed": 0,
                "total_checks_passed": 0,
                "total_tasks_completed": 0,
                "streak_days": 0,
            },
        }

    # Determine active module (first not-completed)
    active_module_id = next(
        (m["module_id"] for m in state["modules"] if not m["completed"]), 6
    )

    return templates.TemplateResponse("training/journey.html", {
        "request": request,
        "user": user,
        "active": "training",
        "lang": user.get("language_pref", "en") if user else "en",
        "state": state,
        "module_titles": MODULE_TITLES,
        "active_module_id": active_module_id,
    })


@app.get("/training/module/{module_id}", response_class=HTMLResponse)
async def training_module(request: Request, module_id: int):
    """Render an individual interactive training module."""
    if module_id < 1 or module_id > 6:
        return RedirectResponse("/training", status_code=302)

    user = _get_user(request)
    # Gate: must complete previous module
    if user and module_id > 1:
        state = db.get_training_state(user["id"])
        prev_done = state["modules"][module_id - 2]["completed"]
        if not prev_done:
            return RedirectResponse("/training", status_code=302)

    return templates.TemplateResponse(f"training/module{module_id}.html", {
        "request": request,
        "user": user,
        "active": "training",
        "lang": user.get("language_pref", "en") if user else "en",
        "module_id": module_id,
        "module_title": MODULE_TITLES[module_id],
        "total_sections": db.MODULE_TOTAL_SECTIONS[module_id],
    })


@app.get("/gaps", response_class=HTMLResponse)
async def gaps(request: Request):
    user = _get_user(request)
    return templates.TemplateResponse("gaps.html", {
        "request": request,
        "user": user,
        "active": "gaps",
        "lang": user.get("language_pref", "en") if user else "en",
    })


@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    user = _get_user(request)
    contributions = []
    personal = {
        "articles_edited": 0,
        "articles_created": 0,
        "total_views": 0,
        "total_views_display": "0",
        "issue_areas": {},
        "max_area": 1,
    }

    if user:
        contributions = db.get_user_contributions(user["id"])
        if contributions:
            personal["articles_edited"] = len(set(
                c["article_title"] for c in contributions if c["contribution_type"] == "Edited"
            ))
            personal["articles_created"] = len(set(
                c["article_title"] for c in contributions
                if c["contribution_type"] in ("Created", "Translated")
            ))
            personal["total_views"] = sum(c.get("pageviews_30d", 0) for c in contributions)
            personal["total_views_display"] = _format_views(personal["total_views"])

            # Issue area breakdown
            areas = {}
            for c in contributions:
                area = c.get("issue_area", "Other")
                areas[area] = areas.get(area, 0) + 1
            personal["issue_areas"] = dict(sorted(areas.items(), key=lambda x: x[1], reverse=True))
            personal["max_area"] = max(areas.values()) if areas else 1

    community = _community_stats_display()

    return templates.TemplateResponse("tracker.html", {
        "request": request,
        "user": user,
        "active": "tracker",
        "lang": user.get("language_pref", "en") if user else "en",
        "personal": personal,
        "contributions": contributions,
        "community": community,
    })


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    badges = db.get_user_badges(user["id"])
    props = db.get_user_props(user["id"])
    all_users = db.get_all_users()

    # Unearned badges
    earned_keys = {b["key"] for b in badges}
    unearned_badges = {
        k: v for k, v in db.BADGE_DEFINITIONS.items() if k not in earned_keys
    }

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "active": "profile",
        "lang": user.get("language_pref", "en"),
        "badges": badges,
        "badge_icons": BADGE_ICONS,
        "unearned_badges": unearned_badges,
        "props": props,
        "all_users": all_users,
    })


# ========== Auth Routes ==========

@app.get("/auth/login")
async def auth_login(request: Request):
    if not auth.is_configured():
        # Dev mode: create a test user and log in directly
        test_user = db.create_or_update_user(
            wiki_username="TestEditor",
            display_name="Test Editor",
        )
        request.session["user_id"] = test_user["id"]
        db.award_badge(test_user["id"], "first_login")
        db.record_weekly_action(test_user["id"])
        return RedirectResponse("/dashboard", status_code=302)

    state = auth.generate_state()
    request.session["oauth_state"] = state
    return RedirectResponse(auth.get_authorize_url(state), status_code=302)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    saved_state = request.session.get("oauth_state", "")
    if not state or state != saved_state:
        return RedirectResponse("/?error=invalid_state", status_code=302)

    # Exchange code for tokens
    token_data = await auth.exchange_code(code)
    if not token_data:
        return RedirectResponse("/?error=token_exchange_failed", status_code=302)

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")

    # Get user profile
    profile = await auth.get_user_profile(access_token)
    if not profile:
        return RedirectResponse("/?error=profile_fetch_failed", status_code=302)

    # Create or update user in database
    user = db.create_or_update_user(
        wiki_username=profile.get("username", ""),
        wiki_user_id=profile.get("sub"),
        display_name=profile.get("username", ""),
        access_token=access_token,
        refresh_token=refresh_token,
    )

    request.session["user_id"] = user["id"]

    # Award first login badge
    if db.award_badge(user["id"], "first_login"):
        await discord_webhook.notify_badge_earned(
            user["display_name"], "First Steps"
        )

    db.record_weekly_action(user["id"])

    return RedirectResponse("/dashboard", status_code=302)


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


# ========== API Routes ==========

# ========== Interactive Training API ==========

# Module titles used for Discord notifications and module header
MODULE_TITLES = {
    1: "Welcome to Wikipedia",
    2: "Your Account and User Page",
    3: "Sandbox = Safe Space",
    4: "Research, Sources, and Your First Live Edit",
    5: "Community and Navigating Disagreement",
    6: "Advanced Editing and What Comes Next",
}


@app.post("/api/training/progress")
async def api_training_progress(request: Request):
    """Save which section a user has reached in a module."""
    user = _get_user(request)
    if not user:
        return {"status": "error", "error": "Not logged in"}
    body = await request.json()
    module_id = int(body.get("module_id", 0))
    section_index = int(body.get("section_index", 0))
    total_sections = int(body.get("total_sections", 0))
    if module_id < 1 or module_id > 6 or section_index < 1 or total_sections < 1:
        return {"status": "error", "error": "Invalid parameters"}
    db.upsert_module_progress(user["id"], module_id, section_index, total_sections)
    db.record_weekly_action(user["id"])
    return {"status": "ok"}


@app.post("/api/training/check")
async def api_training_check(request: Request):
    """Save the result of a comprehension check."""
    user = _get_user(request)
    if not user:
        return {"status": "error", "error": "Not logged in"}
    body = await request.json()
    module_id = int(body.get("module_id", 0))
    check_id = int(body.get("check_id", 0))
    correct = bool(body.get("correct"))
    if module_id < 1 or module_id > 6 or check_id < 1:
        return {"status": "error", "error": "Invalid parameters"}
    db.save_check_result(user["id"], module_id, check_id, correct)
    return {"status": "ok"}


@app.post("/api/training/task")
async def api_training_task(request: Request):
    """Save a task checklist item's completion state."""
    user = _get_user(request)
    if not user:
        return {"status": "error", "error": "Not logged in"}
    body = await request.json()
    module_id = int(body.get("module_id", 0))
    practice_id = str(body.get("practice_id", ""))
    task_index = int(body.get("task_index", -1))
    completed = bool(body.get("completed"))
    if module_id < 1 or module_id > 6 or not practice_id or task_index < 0:
        return {"status": "error", "error": "Invalid parameters"}
    db.save_task_completion(user["id"], module_id, practice_id, task_index, completed)
    return {"status": "ok"}


@app.post("/api/training/complete")
async def api_training_complete(request: Request):
    """Mark a module as completed. Unlocks the next module."""
    user = _get_user(request)
    if not user:
        return {"status": "error", "error": "Not logged in"}
    body = await request.json()
    module_id = int(body.get("module_id", 0))
    if module_id < 1 or module_id > 6:
        return {"status": "error", "error": "Invalid module"}

    newly = db.mark_module_completed(user["id"], module_id)
    # Also record in the legacy training_progress table for dashboard/badge parity
    db.complete_module(user["id"], module_id)

    if newly:
        db.record_weekly_action(user["id"])
        try:
            await discord_webhook.notify_training_complete(
                user["display_name"], MODULE_TITLES.get(module_id, f"Module {module_id}")
            )
        except Exception:
            pass
        try:
            await gamification.check_and_award_badges(user["id"])
        except Exception:
            pass

    next_module = module_id + 1 if module_id < 6 else None
    return {"status": "ok", "next_module": next_module}


@app.get("/api/training/state")
async def api_training_state(request: Request):
    """Return the full training state for the journey tracker + module pages."""
    user = _get_user(request)
    if not user:
        # Provide empty state for anonymous users
        empty_modules = [{
            "module_id": mid,
            "section_index": 1,
            "total_sections": db.MODULE_TOTAL_SECTIONS[mid],
            "completed": False,
            "completed_at": None,
            "updated_at": None,
            "checks_passed": 0,
            "checks_total": 0,
            "tasks_completed": 0,
            "tasks_total": 0,
        } for mid in range(1, 7)]
        return {
            "modules": empty_modules,
            "stats": {
                "modules_completed": 0,
                "total_checks_passed": 0,
                "total_tasks_completed": 0,
                "streak_days": 0,
            },
        }
    return db.get_training_state(user["id"])


@app.get("/api/training/verify-edit")
async def api_verify_edit(request: Request, type: str = "sandbox"):
    """Check if the logged-in user has made a Wikipedia edit.
    type=sandbox → User namespace (ns=2), type=live → Article namespace (ns=0).
    Uses the public MediaWiki API — no OAuth token needed."""
    user = _get_user(request)
    if not user:
        return {"verified": False, "error": "Not logged in"}
    username = user.get("wiki_username", "")
    if not username or username == "TestEditor":
        # Dev auto-login can't be verified against real Wikipedia
        return {"verified": True, "dev": True}

    ns = 2 if type == "sandbox" else 0
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": username,
        "ucnamespace": str(ns),
        "uclimit": "1",
        "ucprop": "title|timestamp",
        "format": "json",
        "formatversion": "2",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(api_url, params=params)
            data = resp.json()
        contribs = data.get("query", {}).get("usercontribs", [])
        if contribs:
            return {
                "verified": True,
                "title": contribs[0].get("title", ""),
                "timestamp": contribs[0].get("timestamp", ""),
            }
        return {"verified": False}
    except Exception as e:
        return {"verified": False, "error": str(e)}


@app.post("/api/tracker/refresh")
async def api_tracker_refresh(request: Request):
    user = _get_user(request)
    if not user:
        return {"success": False, "error": "Not logged in"}

    try:
        contributions = await tracker.fetch_user_contributions_web(
            user["wiki_username"]
        )
        db.save_contributions(user["id"], contributions)
        db.record_weekly_action(user["id"])

        # Check for contribution-based badges
        await gamification.check_and_award_badges(user["id"])

        return {"success": True, "count": len(contributions)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/props/send")
async def api_send_prop(request: Request):
    user = _get_user(request)
    if not user:
        return {"success": False, "error": "Not logged in"}

    body = await request.json()
    to_user_id = body.get("to_user_id")
    message = body.get("message", "").strip()

    if not to_user_id or not message:
        return {"success": False, "error": "Missing recipient or message"}

    if to_user_id == user["id"]:
        return {"success": False, "error": "Can't send props to yourself"}

    success = db.send_prop(user["id"], to_user_id, message)
    if success:
        db.record_weekly_action(user["id"])
        # Check community builder badge
        await gamification.check_and_award_badges(user["id"])

    return {"success": success}


@app.post("/api/set-language")
async def api_set_language(request: Request, lang: str = Query("en", regex="^(en|es)$")):
    user = _get_user(request)
    if user:
        db.update_user_language(user["id"], lang)
    return {"success": True, "lang": lang}


# ========== WikiBridge API Routes (preserved from original) ==========

@app.get("/api/topic-search")
async def topic_search(
    topic: str = Query(..., min_length=1),
    direction: str = Query("es_missing_en", regex="^(es_missing_en|en_missing_es)$"),
    limit: int = Query(100, ge=1, le=500),
):
    if direction == "es_missing_en":
        source_lang, target_lang = "en", "es"
    else:
        source_lang, target_lang = "es", "en"

    try:
        wiki_results = await wikipedia_api.search_and_check_gaps(
            topic, source_lang, target_lang, limit
        )
        gaps = [r for r in wiki_results if r["exists_in_source"] and not r["has_translation"]]
        translated = [r for r in wiki_results if r["has_translation"]]
        total_valid = len(gaps) + len(translated)
        stubs = [r for r in wiki_results if r.get("is_stub")]
        with_issues = [r for r in wiki_results if r.get("quality_issues")]
        target_issues = [r for r in wiki_results if r.get("target_quality") or r.get("target_is_stub")]

        for r in wiki_results:
            r["priority"] = _compute_priority(r)
        wiki_results.sort(key=lambda r: r["priority"], reverse=True)

        return {
            "query": topic,
            "direction": direction,
            "total_searched": len(wiki_results),
            "total_gaps": len(gaps),
            "total_translated": len(translated),
            "coverage_pct": round(len(translated) / max(total_valid, 1) * 100, 1),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "total_target_issues": len(target_issues),
            "results": wiki_results,
        }
    except Exception as e:
        return {"error": str(e), "query": topic, "results": []}


@app.get("/api/category-search")
async def category_search(
    category: str = Query(...),
    direction: str = Query("es_missing_en", regex="^(es_missing_en|en_missing_es)$"),
    limit: int = Query(200, ge=1, le=500),
    deep: bool = Query(False),
):
    if direction == "es_missing_en":
        source_lang, target_lang = "en", "es"
    else:
        source_lang, target_lang = "es", "en"

    try:
        if deep:
            titles = await wikipedia_api.get_category_members_recursive(
                category, source_lang, limit, max_depth=2
            )
        else:
            titles = await wikipedia_api.get_category_members(
                category, source_lang, limit
            )

        if not titles:
            return {"error": f"No articles found in category '{category}'", "results": []}

        results = await wikipedia_api.check_langlinks(titles, source_lang, target_lang)
        gaps = [r for r in results if r["exists_in_source"] and not r["has_translation"]]
        has_translation = [r for r in results if r["has_translation"]]
        stubs = [r for r in results if r.get("is_stub")]
        with_issues = [r for r in results if r.get("quality_issues")]
        target_issues = [r for r in results if r.get("target_quality") or r.get("target_is_stub")]

        for r in results:
            r["priority"] = _compute_priority(r)
        results.sort(key=lambda r: r["priority"], reverse=True)

        return {
            "query": category,
            "direction": direction,
            "total_in_category": len(results),
            "total_gaps": len(gaps),
            "total_translated": len(has_translation),
            "coverage_pct": round(len(has_translation) / max(len(results), 1) * 100, 1),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "total_target_issues": len(target_issues),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "query": category, "results": []}


@app.get("/api/check-articles")
async def check_articles(
    titles: str = Query(...),
    source_lang: str = Query("en", regex="^(en|es)$"),
    target_lang: str = Query("es", regex="^(en|es)$"),
):
    title_list = [t.strip() for t in titles.split("|") if t.strip()]
    if not title_list:
        return {"error": "No titles provided", "results": []}

    try:
        results = await wikipedia_api.check_langlinks(title_list, source_lang, target_lang)
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
            "coverage_pct": round((1 - len(missing) / max(len(results), 1)) * 100, 1),
            "total_stubs": len(stubs),
            "total_quality_issues": len(with_issues),
            "total_target_issues": len(target_issues),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "results": []}


@app.get("/api/export-csv")
async def export_csv(
    data_json: str = Query(...),
):
    import json
    try:
        results = json.loads(data_json)
    except json.JSONDecodeError:
        results = []

    output = io.StringIO()
    if results:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
