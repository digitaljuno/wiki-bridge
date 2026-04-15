from __future__ import annotations

"""SQLite database setup and helpers for ClanDi 2.0."""

import sqlite3
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path(__file__).parent / "clandi.db"


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wiki_username TEXT UNIQUE NOT NULL,
            wiki_user_id INTEGER,
            display_name TEXT,
            organization TEXT DEFAULT 'WikiLatino',
            role TEXT DEFAULT 'newcomer',
            language_pref TEXT DEFAULT 'en',
            access_token TEXT,
            refresh_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS training_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            module_number INTEGER NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, module_number)
        );

        CREATE TABLE IF NOT EXISTS badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            badge_key TEXT NOT NULL,
            earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, badge_key)
        );

        CREATE TABLE IF NOT EXISTS props (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER REFERENCES users(id),
            to_user_id INTEGER REFERENCES users(id),
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            article_title TEXT NOT NULL,
            wiki_lang TEXT NOT NULL,
            contribution_type TEXT,
            bytes_changed INTEGER DEFAULT 0,
            edit_summary TEXT,
            edit_timestamp TIMESTAMP,
            pageviews_30d INTEGER DEFAULT 0,
            issue_area TEXT DEFAULT 'Other',
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS weekly_momentum (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            week_start DATE NOT NULL,
            actions_count INTEGER DEFAULT 0,
            UNIQUE(user_id, week_start)
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            target_articles INTEGER DEFAULT 100,
            target_views INTEGER DEFAULT 1250000,
            start_date DATE,
            end_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Interactive training module tables (ClanDi 2.0) --

        CREATE TABLE IF NOT EXISTS module_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            module_id INTEGER NOT NULL,
            section_index INTEGER NOT NULL DEFAULT 1,
            total_sections INTEGER NOT NULL,
            completed BOOLEAN DEFAULT 0,
            completed_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, module_id)
        );

        CREATE TABLE IF NOT EXISTS check_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            module_id INTEGER NOT NULL,
            check_id INTEGER NOT NULL,
            correct BOOLEAN NOT NULL,
            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, module_id, check_id)
        );

        CREATE TABLE IF NOT EXISTS task_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            module_id INTEGER NOT NULL,
            practice_id TEXT NOT NULL,
            task_index INTEGER NOT NULL,
            completed BOOLEAN DEFAULT 0,
            completed_at TIMESTAMP,
            UNIQUE(user_id, module_id, practice_id, task_index)
        );
    """)
    conn.commit()
    conn.close()


# ---- User helpers ----

def get_user_by_username(wiki_username: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE wiki_username = ?", (wiki_username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_or_update_user(
    wiki_username: str,
    wiki_user_id: int = None,
    display_name: str = None,
    access_token: str = None,
    refresh_token: str = None,
) -> dict:
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM users WHERE wiki_username = ?", (wiki_username,)
    ).fetchone()

    now = datetime.utcnow().isoformat()

    if existing:
        conn.execute(
            """UPDATE users SET
                wiki_user_id = COALESCE(?, wiki_user_id),
                display_name = COALESCE(?, display_name),
                access_token = COALESCE(?, access_token),
                refresh_token = COALESCE(?, refresh_token),
                last_login = ?
            WHERE wiki_username = ?""",
            (wiki_user_id, display_name, access_token, refresh_token, now, wiki_username),
        )
    else:
        conn.execute(
            """INSERT INTO users (wiki_username, wiki_user_id, display_name,
                access_token, refresh_token, last_login)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (wiki_username, wiki_user_id, display_name or wiki_username,
             access_token, refresh_token, now),
        )

    conn.commit()
    row = conn.execute(
        "SELECT * FROM users WHERE wiki_username = ?", (wiki_username,)
    ).fetchone()
    conn.close()
    return dict(row)


def update_user_language(user_id: int, lang: str):
    conn = get_db()
    conn.execute("UPDATE users SET language_pref = ? WHERE id = ?", (lang, user_id))
    conn.commit()
    conn.close()


# ---- Training helpers ----

def get_training_progress(user_id: int) -> list[int]:
    """Return list of completed module numbers."""
    conn = get_db()
    rows = conn.execute(
        "SELECT module_number FROM training_progress WHERE user_id = ? ORDER BY module_number",
        (user_id,),
    ).fetchall()
    conn.close()
    return [r["module_number"] for r in rows]


def complete_module(user_id: int, module_number: int) -> bool:
    """Mark a module as completed. Returns True if newly completed."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO training_progress (user_id, module_number) VALUES (?, ?)",
            (user_id, module_number),
        )
        conn.commit()
        changed = conn.total_changes > 0
        conn.close()
        return changed
    except Exception:
        conn.close()
        return False


# ---- Badge helpers ----

BADGE_DEFINITIONS = {
    "first_login": {
        "name_en": "First Steps",
        "name_es": "Primeros Pasos",
        "desc_en": "Logged into ClanDi for the first time",
        "desc_es": "Iniciaste sesion en ClanDi por primera vez",
        "icon": "footprints",
    },
    "training_complete": {
        "name_en": "Wiki Scholar",
        "name_es": "Wiki Erudito/a",
        "desc_en": "Completed all 6 Wiki 101 training modules",
        "desc_es": "Completaste los 6 modulos de Wiki 101",
        "icon": "graduation-cap",
    },
    "first_edit": {
        "name_en": "First Live Edit",
        "name_es": "Primera Edicion",
        "desc_en": "Made your first Wikipedia edit",
        "desc_es": "Hiciste tu primera edicion en Wikipedia",
        "icon": "pencil",
    },
    "puente": {
        "name_en": "Puente",
        "name_es": "Puente",
        "desc_en": "First translation between EN and ES Wikipedia",
        "desc_es": "Primera traduccion entre Wikipedia EN y ES",
        "icon": "bridge",
    },
    "sourcing_pro": {
        "name_en": "Sourcing Pro",
        "name_es": "Experto/a en Fuentes",
        "desc_en": "Made 5+ properly cited edits",
        "desc_es": "Hiciste 5+ ediciones con citas apropiadas",
        "icon": "book-open",
    },
    "gap_closer": {
        "name_en": "Gap Closer",
        "name_es": "Cierra Brechas",
        "desc_en": "Improved a high-priority content gap article",
        "desc_es": "Mejoraste un articulo de brecha de contenido prioritario",
        "icon": "target",
    },
    "momentum_3": {
        "name_en": "3-Week Momentum",
        "name_es": "Impulso de 3 Semanas",
        "desc_en": "Active for 3 consecutive weeks",
        "desc_es": "Activo/a durante 3 semanas consecutivas",
        "icon": "flame",
    },
    "community_builder": {
        "name_en": "Community Builder",
        "name_es": "Constructor/a de Comunidad",
        "desc_en": "Sent 5+ props to other editors",
        "desc_es": "Enviaste 5+ reconocimientos a otros editores",
        "icon": "heart-handshake",
    },
    "module_1": {
        "name_en": "Wiki Explorer",
        "name_es": "Explorador/a Wiki",
        "desc_en": "Completed Module 1: Welcome to Wikimedia",
        "desc_es": "Completaste Modulo 1: Bienvenido a Wikimedia",
        "icon": "compass",
    },
    "module_3": {
        "name_en": "Sandbox Builder",
        "name_es": "Constructor/a de Sandbox",
        "desc_en": "Completed Module 3: Sandbox = Safe Space",
        "desc_es": "Completaste Modulo 3: Sandbox = Espacio Seguro",
        "icon": "hammer",
    },
}


def get_user_badges(user_id: int) -> list[dict]:
    """Return list of badge dicts with definitions."""
    conn = get_db()
    rows = conn.execute(
        "SELECT badge_key, earned_at FROM badges WHERE user_id = ? ORDER BY earned_at",
        (user_id,),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        defn = BADGE_DEFINITIONS.get(r["badge_key"], {})
        result.append({
            "key": r["badge_key"],
            "earned_at": r["earned_at"],
            **defn,
        })
    return result


def award_badge(user_id: int, badge_key: str) -> bool:
    """Award a badge. Returns True if newly awarded."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO badges (user_id, badge_key) VALUES (?, ?)",
            (user_id, badge_key),
        )
        conn.commit()
        changed = conn.total_changes > 0
        conn.close()
        return changed
    except Exception:
        conn.close()
        return False


# ---- Props helpers ----

def send_prop(from_user_id: int, to_user_id: int, message: str) -> bool:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO props (from_user_id, to_user_id, message) VALUES (?, ?, ?)",
            (from_user_id, to_user_id, message),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def get_user_props(user_id: int, limit: int = 20) -> list[dict]:
    """Get props received by a user."""
    conn = get_db()
    rows = conn.execute(
        """SELECT p.*, u.wiki_username as from_username, u.display_name as from_display
        FROM props p JOIN users u ON p.from_user_id = u.id
        WHERE p.to_user_id = ? ORDER BY p.created_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_props_sent(user_id: int) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM props WHERE from_user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


# ---- Contribution helpers ----

def save_contributions(user_id: int, contributions: list[dict]):
    """Bulk save contribution records."""
    conn = get_db()
    # Clear old contributions for this user
    conn.execute("DELETE FROM contributions WHERE user_id = ?", (user_id,))
    for c in contributions:
        conn.execute(
            """INSERT INTO contributions
            (user_id, article_title, wiki_lang, contribution_type, bytes_changed,
             edit_summary, edit_timestamp, pageviews_30d, issue_area)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, c["article_title"], c["wiki_lang"], c["contribution_type"],
             c.get("bytes_changed", 0), c.get("edit_summary", ""),
             c.get("edit_timestamp", ""), c.get("pageviews_30d", 0),
             c.get("issue_area", "Other")),
        )
    conn.commit()
    conn.close()


def get_user_contributions(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM contributions WHERE user_id = ? ORDER BY edit_timestamp DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_community_stats() -> dict:
    """Get aggregate community stats for the mission dashboard."""
    conn = get_db()

    total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
    total_contributions = conn.execute("SELECT COUNT(*) as cnt FROM contributions").fetchone()["cnt"]
    total_articles = conn.execute(
        "SELECT COUNT(DISTINCT article_title || wiki_lang) as cnt FROM contributions"
    ).fetchone()["cnt"]
    total_views = conn.execute(
        "SELECT COALESCE(SUM(pageviews_30d), 0) as total FROM contributions"
    ).fetchone()["total"]
    total_badges = conn.execute("SELECT COUNT(*) as cnt FROM badges").fetchone()["cnt"]
    total_modules = conn.execute("SELECT COUNT(*) as cnt FROM training_progress").fetchone()["cnt"]

    conn.close()
    return {
        "total_users": total_users,
        "total_contributions": total_contributions,
        "total_articles": total_articles,
        "total_views": total_views,
        "total_badges": total_badges,
        "total_modules_completed": total_modules,
    }


# ---- Momentum helpers ----

def record_weekly_action(user_id: int):
    """Record an action for the current week."""
    today = date.today()
    # Week starts Monday
    week_start = today - __import__("datetime").timedelta(days=today.weekday())
    conn = get_db()
    conn.execute(
        """INSERT INTO weekly_momentum (user_id, week_start, actions_count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, week_start) DO UPDATE SET actions_count = actions_count + 1""",
        (user_id, week_start.isoformat()),
    )
    conn.commit()
    conn.close()


def get_momentum_weeks(user_id: int, limit: int = 12) -> list[dict]:
    """Get recent weekly momentum data."""
    conn = get_db()
    rows = conn.execute(
        """SELECT week_start, actions_count FROM weekly_momentum
        WHERE user_id = ? ORDER BY week_start DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_consecutive_weeks(user_id: int) -> int:
    """Count current consecutive active weeks."""
    weeks = get_momentum_weeks(user_id, limit=52)
    if not weeks:
        return 0

    today = date.today()
    current_week = today - __import__("datetime").timedelta(days=today.weekday())

    count = 0
    for w in weeks:
        expected = current_week - __import__("datetime").timedelta(weeks=count)
        if w["week_start"] == expected.isoformat():
            count += 1
        else:
            break
    return count


# ---- All users list (for props, directory) ----

def get_all_users() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, wiki_username, display_name, organization, role FROM users ORDER BY display_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Interactive module helpers ----

# Total sections per module (source: reference HTML files)
MODULE_TOTAL_SECTIONS = {1: 6, 2: 6, 3: 7, 4: 6, 5: 6, 6: 5}


def upsert_module_progress(user_id: int, module_id: int, section_index: int,
                            total_sections: int) -> None:
    """Upsert a user's progress within a module (last-reached section)."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO module_progress
            (user_id, module_id, section_index, total_sections, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, module_id) DO UPDATE SET
              section_index = MAX(section_index, excluded.section_index),
              total_sections = excluded.total_sections,
              updated_at = excluded.updated_at""",
        (user_id, module_id, section_index, total_sections, now),
    )
    conn.commit()
    conn.close()


def mark_module_completed(user_id: int, module_id: int) -> bool:
    """Mark a module's interactive progress as completed. Returns True if newly completed."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    total = MODULE_TOTAL_SECTIONS.get(module_id, 6)
    existing = conn.execute(
        "SELECT completed FROM module_progress WHERE user_id = ? AND module_id = ?",
        (user_id, module_id),
    ).fetchone()
    if existing and existing["completed"]:
        conn.close()
        return False
    conn.execute(
        """INSERT INTO module_progress
            (user_id, module_id, section_index, total_sections, completed, completed_at, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?)
           ON CONFLICT(user_id, module_id) DO UPDATE SET
              completed = 1,
              completed_at = excluded.completed_at,
              section_index = excluded.section_index,
              updated_at = excluded.updated_at""",
        (user_id, module_id, total, total, now, now),
    )
    conn.commit()
    conn.close()
    return True


def save_check_result(user_id: int, module_id: int, check_id: int, correct: bool) -> None:
    """Save a comprehension check result (one row per (user, module, check))."""
    conn = get_db()
    conn.execute(
        """INSERT INTO check_results (user_id, module_id, check_id, correct)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, module_id, check_id) DO UPDATE SET
              correct = excluded.correct,
              answered_at = CURRENT_TIMESTAMP""",
        (user_id, module_id, check_id, 1 if correct else 0),
    )
    conn.commit()
    conn.close()


def save_task_completion(user_id: int, module_id: int, practice_id: str,
                          task_index: int, completed: bool) -> None:
    """Save a task checklist item's completion state."""
    conn = get_db()
    now = datetime.utcnow().isoformat() if completed else None
    conn.execute(
        """INSERT INTO task_completions
            (user_id, module_id, practice_id, task_index, completed, completed_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, module_id, practice_id, task_index) DO UPDATE SET
              completed = excluded.completed,
              completed_at = excluded.completed_at""",
        (user_id, module_id, practice_id, task_index, 1 if completed else 0, now),
    )
    conn.commit()
    conn.close()


def get_module_progress_row(user_id: int, module_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM module_progress WHERE user_id = ? AND module_id = ?",
        (user_id, module_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_check_results(user_id: int, module_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT check_id, correct FROM check_results WHERE user_id = ? AND module_id = ?",
        (user_id, module_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task_completions(user_id: int, module_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT practice_id, task_index, completed FROM task_completions
           WHERE user_id = ? AND module_id = ?""",
        (user_id, module_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_training_state(user_id: int) -> dict:
    """Build the full training state dict for the journey tracker and module pages."""
    conn = get_db()
    mod_rows = conn.execute(
        "SELECT * FROM module_progress WHERE user_id = ?", (user_id,)
    ).fetchall()
    chk_rows = conn.execute(
        """SELECT module_id,
                  SUM(CASE WHEN correct THEN 1 ELSE 0 END) as passed,
                  COUNT(*) as total
           FROM check_results WHERE user_id = ? GROUP BY module_id""",
        (user_id,),
    ).fetchall()
    task_rows = conn.execute(
        """SELECT module_id,
                  SUM(CASE WHEN completed THEN 1 ELSE 0 END) as done,
                  COUNT(*) as total
           FROM task_completions WHERE user_id = ? GROUP BY module_id""",
        (user_id,),
    ).fetchall()
    conn.close()

    mod_map = {r["module_id"]: dict(r) for r in mod_rows}
    chk_map = {r["module_id"]: dict(r) for r in chk_rows}
    task_map = {r["module_id"]: dict(r) for r in task_rows}

    modules = []
    modules_completed = 0
    total_checks_passed = 0
    total_tasks_completed = 0

    for mid in range(1, 7):
        mp = mod_map.get(mid, {})
        ch = chk_map.get(mid, {})
        tk = task_map.get(mid, {})
        completed = bool(mp.get("completed"))
        if completed:
            modules_completed += 1
        checks_passed = int(ch.get("passed") or 0)
        checks_total = int(ch.get("total") or 0)
        tasks_done = int(tk.get("done") or 0)
        tasks_total = int(tk.get("total") or 0)
        total_checks_passed += checks_passed
        total_tasks_completed += tasks_done

        modules.append({
            "module_id": mid,
            "section_index": int(mp.get("section_index") or 1),
            "total_sections": int(mp.get("total_sections") or MODULE_TOTAL_SECTIONS[mid]),
            "completed": completed,
            "completed_at": mp.get("completed_at"),
            "updated_at": mp.get("updated_at"),
            "checks_passed": checks_passed,
            "checks_total": checks_total,
            "tasks_completed": tasks_done,
            "tasks_total": tasks_total,
        })

    streak_days = get_consecutive_weeks(user_id)  # proxy: consecutive active weeks
    return {
        "modules": modules,
        "stats": {
            "modules_completed": modules_completed,
            "total_checks_passed": total_checks_passed,
            "total_tasks_completed": total_tasks_completed,
            "streak_days": streak_days,
        },
    }


# Initialize on import
init_db()
