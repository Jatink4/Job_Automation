"""
notifier.py — Telegram notifications for job results.

Sends best job matches via Telegram with direct links to apply.
"""

from __future__ import annotations

from pathlib import Path
from loguru import logger

import config


async def send_telegram_results(
    passed_jobs: list[dict],
    failed_jobs: list[dict],
    results_file: Path,
    applied: list[dict] | None = None,
) -> None:
    """Send best matches (+ applied list) via Telegram."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured — skipping notification")
        return

    try:
        from telegram import Bot
    except ImportError:
        logger.warning("python-telegram-bot not installed — skipping Telegram")
        return

    sorted_jobs = sorted(passed_jobs, key=lambda x: x.get("ai_score", 0), reverse=True)
    top_jobs = sorted_jobs[:10]
    message = _format_results_message(top_jobs, passed_jobs, failed_jobs, applied or [])

    try:
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="HTML",
        )
        logger.info("✓ Telegram notification sent with {} top jobs", len(top_jobs))

        # Send interactive action cards for top review-pending matches
        from core.telegram_bot import send_interactive_card
        for job in top_jobs[:5]:
            await send_interactive_card(job, bot=bot)
            await asyncio.sleep(0.3)

    except Exception as exc:
        logger.error("Failed to send Telegram message: {}", exc)


def _format_results_message(
    top_jobs: list[dict],
    all_passed: list[dict],
    all_failed: list[dict],
    applied: list[dict],
) -> str:
    lines = [
        "<b>Job Bot Results</b>",
        "",
        f"Best Matches: <b>{len(all_passed)}</b>",
        f"Filtered Out: <b>{len(all_failed)}</b>",
        f"Auto-Applied: <b>{len(applied)}</b>",
        "",
        "<b>Top matches:</b>",
    ]

    for i, job in enumerate(top_jobs, 1):
        title = job.get("title", "N/A")
        company = job.get("company", "N/A")
        score = job.get("ai_score", 0)
        url = job.get("url", "#")
        source = job.get("source", "unknown")
        status = job.get("apply_status", "")
        status_bit = f" | {status}" if status else ""
        lines.append(f"\n{i}. <a href='{url}'><b>{title}</b></a>")
        lines.append(f"   {company} | score {score}{status_bit} | {source}")

    if applied:
        lines.extend(["", "<b>Applied this run:</b>"])
        for job in applied[:10]:
            lines.append(
                f"• <a href='{job.get('url', '#')}'>{job.get('title', '?')}</a> "
                f"— {job.get('company', '?')}"
            )

    return "\n".join(lines)
