from __future__ import annotations

"""ClanDi 2.0 — Wikipedia Editor Training & Impact Platform.

Expands WikiBridge into a full training, tracking, and gamification app.
"""

import csv
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


# Training module content with quizzes
TRAINING_MODULES = [
    {
        "number": 1,
        "title": "Welcome to Wikimedia",
        "track": "Wiki Basics",
        "content_html": """
        <h4>What is Wikimedia?</h4>
        <p>Wikimedia is the ecosystem of free knowledge projects — Wikipedia, Wikimedia Commons, Wikidata, and more. Wikipedia alone gets over <strong>15 billion page views per month</strong>, making it one of the most visited websites on Earth.</p>
        <h4>Why does this matter?</h4>
        <p>Wikipedia shapes what billions of people understand about the world. When topics about Latino communities, reproductive justice, and BIPOC experiences are missing or poorly written, it affects real-world perceptions and decisions.</p>
        <h4>The 5 Pillars of Wikipedia</h4>
        <ol>
            <li><strong>Wikipedia is an encyclopedia</strong> — not a soapbox, blog, or directory</li>
            <li><strong>Neutral Point of View (NPOV)</strong> — present all significant views fairly</li>
            <li><strong>Free content</strong> — everything is freely licensed</li>
            <li><strong>Respect and civility</strong> — treat other editors with respect</li>
            <li><strong>No firm rules</strong> — policies are guidelines, use good judgment</li>
        </ol>
        <h4>Your Task</h4>
        <p>Create your Wikipedia account if you haven't already. Explore the five pillars and think about what topics you'd like to improve.</p>
        """,
        "videos": [
            {"title": "What is Wikipedia? (Wikimedia Foundation)", "url": "https://www.youtube.com/watch?v=xQ4ba28-oGs"},
        ],
        "quiz": [
            {
                "question": "How many page views does Wikipedia get per month?",
                "options": ["1 billion", "5 billion", "15 billion", "50 billion"],
                "correct": 2,
            },
            {
                "question": "Which of these is one of Wikipedia's 5 Pillars?",
                "options": [
                    "Only experts can edit",
                    "Neutral Point of View (NPOV)",
                    "English is the primary language",
                    "Editors must use their real names",
                ],
                "correct": 1,
            },
            {
                "question": "Why is editing Wikipedia important for Latino communities?",
                "options": [
                    "It pays well",
                    "It's required by law",
                    "Underrepresented stories affect real-world perceptions",
                    "Wikipedia only covers mainstream topics",
                ],
                "correct": 2,
            },
        ],
    },
    {
        "number": 2,
        "title": "Creating an Account & Your User Page",
        "track": "Wiki Basics",
        "content_html": """
        <h4>Setting Up Your Wikipedia Account</h4>
        <p>Your Wikipedia identity is important. Choose a username that represents you professionally — it will be visible on every edit you make.</p>
        <h4>Your User Page</h4>
        <p>Your user page is your personal space on Wikipedia. It's where you can:</p>
        <ul>
            <li>Introduce yourself to the community</li>
            <li>List your areas of interest and expertise</li>
            <li>Display userboxes showing your affiliations</li>
            <li>Keep track of articles you're working on</li>
        </ul>
        <h4>Editing Basics</h4>
        <p>Wikipedia uses a visual editor and a source editor. The <strong>visual editor</strong> works like a word processor — great for beginners. The <strong>source editor</strong> uses wikitext markup for more control.</p>
        <h4>Your Task</h4>
        <p>Create or update your user page. Add the WikiLatinos userbox and list 2-3 topics you want to work on.</p>
        """,
        "videos": [],
        "quiz": [
            {
                "question": "What is a user page on Wikipedia?",
                "options": [
                    "A page only admins can see",
                    "Your personal space to introduce yourself and list interests",
                    "A page that tracks your errors",
                    "A messaging system between editors",
                ],
                "correct": 1,
            },
            {
                "question": "Which editor is best for beginners?",
                "options": [
                    "Source editor",
                    "Command-line editor",
                    "Visual editor",
                    "HTML editor",
                ],
                "correct": 2,
            },
        ],
    },
    {
        "number": 3,
        "title": "Sandbox = Safe Space",
        "track": "Content Creation",
        "content_html": """
        <h4>What is the Sandbox?</h4>
        <p>Every Wikipedia user has a <strong>sandbox</strong> — a private draft space where you can practice editing without affecting live articles. Think of it as your personal lab.</p>
        <h4>How to Use Your Sandbox</h4>
        <ol>
            <li>Navigate to your sandbox: <code>User:YourUsername/sandbox</code></li>
            <li>Click "Edit" to start writing</li>
            <li>Practice formatting: headings, bold, italic, links, references</li>
            <li>Save your work — it's only visible to you until you move it</li>
        </ol>
        <h4>Key Formatting</h4>
        <ul>
            <li><code>== Heading ==</code> for section headers</li>
            <li><code>'''bold'''</code> for bold text</li>
            <li><code>''italic''</code> for italic text</li>
            <li><code>[[Article Name]]</code> for internal links</li>
            <li><code>[https://example.com Text]</code> for external links</li>
        </ul>
        <h4>Your Task</h4>
        <p>Go to your sandbox and write a 2-3 paragraph draft about a topic you care about. Include at least one heading, one internal link, and one reference.</p>
        """,
        "videos": [],
        "quiz": [
            {
                "question": "What is the correct wikitext for making text bold?",
                "options": [
                    "<b>bold</b>",
                    "**bold**",
                    "'''bold'''",
                    "__bold__",
                ],
                "correct": 2,
            },
            {
                "question": "What is the sandbox used for?",
                "options": [
                    "Publishing articles directly",
                    "Messaging other editors",
                    "Practicing editing without affecting live articles",
                    "Reporting vandalism",
                ],
                "correct": 2,
            },
            {
                "question": "How do you create an internal link to another Wikipedia article?",
                "options": [
                    "[Article Name]",
                    "[[Article Name]]",
                    "<link>Article Name</link>",
                    "(Article Name)",
                ],
                "correct": 1,
            },
        ],
    },
    {
        "number": 4,
        "title": "Research & Reliable Sources",
        "track": "Content Creation",
        "content_html": """
        <h4>Why Sources Matter</h4>
        <p>Wikipedia's power comes from <strong>verifiability</strong>. Every claim should be backed by a reliable, published source. This is what separates Wikipedia from opinion blogs.</p>
        <h4>What Counts as a Reliable Source?</h4>
        <ul>
            <li><strong>Yes:</strong> Peer-reviewed journals, major newspapers, academic books, government reports</li>
            <li><strong>Sometimes:</strong> Reputable magazines, established news outlets, organizational reports</li>
            <li><strong>No:</strong> Personal blogs, social media, self-published content, press releases</li>
        </ul>
        <h4>Adding References</h4>
        <p>Use the <code>&lt;ref&gt;</code> tag or the visual editor's "Cite" button to add inline citations. Every paragraph of content should have at least one reference.</p>
        <h4>Finding Sources for Latino/BIPOC Topics</h4>
        <p>Academic databases like JSTOR, Google Scholar, and the Hispanic American Historical Review are great starting points. Local and community newspapers are also valuable for topics mainstream media doesn't cover.</p>
        <h4>Your Task</h4>
        <p>Find 3 reliable sources for the topic you drafted in your sandbox. Add proper citations using the reference format.</p>
        """,
        "videos": [],
        "quiz": [
            {
                "question": "Which of these is NOT a reliable source for Wikipedia?",
                "options": [
                    "The New York Times",
                    "A peer-reviewed journal article",
                    "A personal blog post",
                    "A government census report",
                ],
                "correct": 2,
            },
            {
                "question": "What Wikipedia principle requires every claim to be backed by sources?",
                "options": [
                    "Notability",
                    "Verifiability",
                    "Consensus",
                    "Neutrality",
                ],
                "correct": 1,
            },
            {
                "question": "Which database is good for finding sources on Latino history?",
                "options": [
                    "Reddit",
                    "Wikipedia itself",
                    "JSTOR and Google Scholar",
                    "Twitter/X",
                ],
                "correct": 2,
            },
        ],
    },
    {
        "number": 5,
        "title": "Making Your First Live Edit",
        "track": "Community & Leadership",
        "content_html": """
        <h4>From Sandbox to Live Wikipedia</h4>
        <p>You've practiced in your sandbox — now it's time to make a real edit. Start small: fix a typo, add a missing reference, or expand a stub article.</p>
        <h4>Best Practices for Your First Edit</h4>
        <ul>
            <li><strong>Start small:</strong> Don't rewrite an entire article on day one</li>
            <li><strong>Write clear edit summaries:</strong> Explain what you changed and why</li>
            <li><strong>Be bold but careful:</strong> Wikipedia encourages boldness, but respect existing content</li>
            <li><strong>Watch the article:</strong> Click "Watch" to monitor changes after your edit</li>
        </ul>
        <h4>Dealing with Reverts</h4>
        <p>Sometimes other editors may undo your changes. Don't take it personally — check the reason, discuss on the article's Talk page, and learn from it. This is how Wikipedia's collaborative editing works.</p>
        <h4>Your Task</h4>
        <p>Make your first live edit! Use WikiBridge to find a gap or stub, then improve it. Remember to add sources and write a clear edit summary.</p>
        """,
        "videos": [],
        "quiz": [
            {
                "question": "What should you include with every edit you make?",
                "options": [
                    "Your real name",
                    "A clear edit summary explaining what you changed",
                    "A link to your social media",
                    "An apology for editing",
                ],
                "correct": 1,
            },
            {
                "question": "If another editor reverts your change, what should you do?",
                "options": [
                    "Revert their revert immediately",
                    "Give up editing forever",
                    "Check the reason and discuss on the Talk page",
                    "Report them to Wikipedia admins",
                ],
                "correct": 2,
            },
        ],
    },
    {
        "number": 6,
        "title": "Translation & Community Leadership",
        "track": "Community & Leadership",
        "content_html": """
        <h4>Bridging the Language Gap</h4>
        <p>One of the most impactful things you can do is <strong>translate articles between English and Spanish Wikipedia</strong>. Many important topics exist in one language but not the other.</p>
        <h4>Using the Content Translation Tool</h4>
        <ol>
            <li>Go to <code>Special:ContentTranslation</code> on Wikipedia</li>
            <li>Choose a source article and target language</li>
            <li>The tool provides machine translation as a starting point</li>
            <li>Review and improve every paragraph — don't just publish machine translation</li>
            <li>Adapt cultural context as needed</li>
        </ol>
        <h4>Becoming a Community Leader</h4>
        <p>As you gain experience, you can:</p>
        <ul>
            <li>Mentor new editors in your community</li>
            <li>Organize edit-a-thons and training sessions</li>
            <li>Contribute to WikiProject discussions</li>
            <li>Apply for grants to support your editing campaigns</li>
        </ul>
        <h4>Your Task</h4>
        <p>Use WikiBridge to find a high-priority article missing in Spanish (or English). Start translating it using the Content Translation tool, or expand an existing stub with properly sourced content.</p>
        """,
        "videos": [],
        "quiz": [
            {
                "question": "When using the Content Translation tool, what should you do with the machine translation?",
                "options": [
                    "Publish it directly — it's good enough",
                    "Review and improve every paragraph before publishing",
                    "Delete it and start from scratch",
                    "Only fix spelling errors",
                ],
                "correct": 1,
            },
            {
                "question": "What Wikipedia tool helps you translate articles between languages?",
                "options": [
                    "Google Translate",
                    "Special:ContentTranslation",
                    "WikiBridge",
                    "The Visual Editor",
                ],
                "correct": 1,
            },
            {
                "question": "Which of these is a way to grow as a Wikipedia community leader?",
                "options": [
                    "Only edit articles, never interact with others",
                    "Organize edit-a-thons and mentor new editors",
                    "Delete articles you disagree with",
                    "Avoid WikiProject discussions",
                ],
                "correct": 1,
            },
        ],
    },
]


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
    user = _get_user(request)
    completed = db.get_training_progress(user["id"]) if user else []
    next_module = min((m for m in range(1, 7) if m not in completed), default=7)

    return templates.TemplateResponse("training.html", {
        "request": request,
        "user": user,
        "active": "training",
        "lang": user.get("language_pref", "en") if user else "en",
        "modules": TRAINING_MODULES,
        "completed": completed,
        "next_module": next_module,
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

@app.post("/api/training/complete/{module_number}")
async def api_complete_module(request: Request, module_number: int):
    user = _get_user(request)
    if not user:
        return {"success": False, "error": "Not logged in"}

    if module_number < 1 or module_number > 6:
        return {"success": False, "error": "Invalid module number"}

    # Check prerequisites — must complete previous modules first
    completed = db.get_training_progress(user["id"])
    if module_number > 1 and (module_number - 1) not in completed:
        return {"success": False, "error": "Complete previous modules first"}

    if module_number in completed:
        return {"success": True, "already_completed": True}

    # Validate quiz answers
    body = await request.json()
    answers = body.get("answers", [])

    module_info = next((m for m in TRAINING_MODULES if m["number"] == module_number), None)
    if not module_info:
        return {"success": False, "error": "Module not found"}

    quiz = module_info.get("quiz", [])
    if quiz:
        if len(answers) != len(quiz):
            return {"success": False, "error": "Please answer all quiz questions"}

        wrong = []
        for i, q in enumerate(quiz):
            if i >= len(answers) or answers[i] != q["correct"]:
                wrong.append(i + 1)

        if wrong:
            return {
                "success": False,
                "error": f"Incorrect answers on question(s) {', '.join(str(w) for w in wrong)}. Review the material and try again.",
                "wrong": wrong,
            }

    newly_completed = db.complete_module(user["id"], module_number)
    if newly_completed:
        db.record_weekly_action(user["id"])

        if module_info:
            await discord_webhook.notify_training_complete(
                user["display_name"], module_info["title"]
            )

        # Check gamification badges
        await gamification.check_and_award_badges(user["id"])

    return {"success": True}


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
