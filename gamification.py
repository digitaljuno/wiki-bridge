from __future__ import annotations

"""Gamification logic for ClanDi 2.0.

Checks user state and awards badges when criteria are met.
"""

import database as db
import discord_webhook


async def check_and_award_badges(user_id: int):
    """Check all badge criteria and award any that are newly earned."""
    user = db.get_user_by_id(user_id)
    if not user:
        return

    display_name = user.get("display_name", user["wiki_username"])
    completed = db.get_training_progress(user_id)
    contributions = db.get_user_contributions(user_id)
    consecutive = db.get_consecutive_weeks(user_id)
    props_sent = db.count_props_sent(user_id)

    # Module-specific badges
    if 1 in completed:
        if db.award_badge(user_id, "module_1"):
            await discord_webhook.notify_badge_earned(display_name, "Wiki Explorer")

    if 3 in completed:
        if db.award_badge(user_id, "module_3"):
            await discord_webhook.notify_badge_earned(display_name, "Sandbox Builder")

    # All training complete
    if len(completed) >= 6:
        if db.award_badge(user_id, "training_complete"):
            await discord_webhook.notify_badge_earned(display_name, "Wiki Scholar")

    # Contribution-based badges
    if contributions:
        # First edit
        if db.award_badge(user_id, "first_edit"):
            await discord_webhook.notify_badge_earned(display_name, "First Live Edit")

        # Puente — has a translation
        translated = [c for c in contributions if c.get("contribution_type") == "Translated"]
        if translated:
            if db.award_badge(user_id, "puente"):
                await discord_webhook.notify_badge_earned(display_name, "Puente")

        # Sourcing pro — 5+ edits (proxy for properly cited edits)
        if len(contributions) >= 5:
            if db.award_badge(user_id, "sourcing_pro"):
                await discord_webhook.notify_badge_earned(display_name, "Sourcing Pro")

        # Gap closer — any article with high pageviews
        high_impact = [c for c in contributions if c.get("pageviews_30d", 0) >= 1000]
        if high_impact:
            if db.award_badge(user_id, "gap_closer"):
                await discord_webhook.notify_badge_earned(display_name, "Gap Closer")

    # Momentum badge — 3 consecutive weeks
    if consecutive >= 3:
        if db.award_badge(user_id, "momentum_3"):
            await discord_webhook.notify_badge_earned(display_name, "3-Week Momentum")

    # Community builder — 5+ props sent
    if props_sent >= 5:
        if db.award_badge(user_id, "community_builder"):
            await discord_webhook.notify_badge_earned(display_name, "Community Builder")

    # Update user role based on progression
    await _update_role(user_id, completed, contributions, consecutive)


async def _update_role(
    user_id: int,
    completed: list[int],
    contributions: list[dict],
    consecutive: int,
):
    """Update user role based on achievements."""
    user = db.get_user_by_id(user_id)
    if not user:
        return

    current_role = user.get("role", "newcomer")

    # Role progression logic
    new_role = "newcomer"

    if len(completed) >= 2 or len(contributions) >= 1:
        new_role = "editor"

    if len(completed) >= 4 and len(contributions) >= 5:
        new_role = "contributor"

    if len(completed) >= 6 and len(contributions) >= 15 and consecutive >= 3:
        new_role = "mentor"

    if len(completed) >= 6 and len(contributions) >= 30 and consecutive >= 8:
        new_role = "leader"

    # Only upgrade, never downgrade
    role_order = ["newcomer", "editor", "contributor", "mentor", "leader"]
    if role_order.index(new_role) > role_order.index(current_role):
        conn = db.get_db()
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        conn.close()
