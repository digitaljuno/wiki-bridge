"""Discord webhook integration for ClanDi 2.0.

Posts automated updates to a WikiLatino Discord channel.
Set DISCORD_WEBHOOK_URL environment variable.
"""

import os

import httpx

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "ClanDi/2.0",
}


async def post_to_discord(message: str) -> bool:
    """Post a message to the configured Discord webhook. Returns True on success."""
    if not WEBHOOK_URL:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                WEBHOOK_URL,
                json={"content": message},
                headers=HEADERS,
            )
            return resp.status_code in (200, 204)
    except Exception:
        return False


async def notify_badge_earned(username: str, badge_name: str):
    await post_to_discord(f"🏅 **{username}** just earned **'{badge_name}'**!")


async def notify_training_complete(username: str, module_name: str):
    await post_to_discord(f"🎓 **{username}** completed **{module_name}**")


async def notify_campaign_milestone(campaign: str, current: int, target: int):
    pct = round(current / max(target, 1) * 100)
    await post_to_discord(f"🎯 **{campaign}**: {current}/{target} articles ({pct}%)")


async def notify_weekly_summary(articles: int, views: int, new_users: int):
    views_str = f"{views:,}" if views < 1_000_000 else f"{views / 1_000_000:.1f}M"
    await post_to_discord(
        f"📊 **This week**: {articles} articles improved, "
        f"{views_str} pageviews, {new_users} new editors joined"
    )
