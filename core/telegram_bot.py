"""
core/telegram_bot.py — Interactive Telegram Approval Bot & Notification Hub.

Features:
- Dispatches interactive cards with [Approve & Apply] and [Reject] inline buttons.
- Handles Telegram button taps directly from your phone.
- Automatically triggers Playwright application submission upon approval.
- Supports Telegram commands: /start, /status, /pending, /apply.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import config
from config import load_resume
from core.db import (
    get_job_by_id,
    get_jobs_by_status,
    get_pending_review_jobs,
    get_summary_metrics,
    update_job_status,
)


async def send_interactive_card(job: dict[str, Any], bot: Optional[Any] = None) -> None:
    """Send an interactive job card with approval buttons to Telegram."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return

    from telegram import Bot

    if bot is None:
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    db_id = job.get("db_id") or job.get("id")
    title = job.get("title", "Software Role")
    company = job.get("company", "Company")
    location = job.get("location", "India")
    score = job.get("score") or job.get("ai_score", 0)
    salary = job.get("salary_raw") or "₹12+ LPA"
    url = job.get("url") or job.get("manual_apply_url") or "https://linkedin.com/jobs/"
    source = str(job.get("source", "linkedin")).upper()
    profile_name = job.get("profile_name") or "Job Profile"

    text = (
        f"🌟 <b>New High Match Discovered!</b>\n\n"
        f"💼 <b>{title}</b>\n"
        f"🏢 <b>{company}</b>\n"
        f"📍 Location: <b>{location}</b>\n"
        f"💰 Salary: <b>{salary}</b>\n"
        f"🎯 Match Score: <b>{score}/100</b> ({profile_name})\n"
        f"🌐 Platform: <b>{source}</b>\n"
    )

    buttons = []
    if db_id:
        buttons.append([
            InlineKeyboardButton("✅ Approve & Apply", callback_data=f"approve_{db_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{db_id}"),
        ])
    buttons.append([
        InlineKeyboardButton("🔗 Open Job Listing", url=url),
    ])

    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        logger.info("Sent interactive Telegram card for '{}' at '{}'", title, company)
    except Exception as exc:
        logger.error("Failed to send interactive Telegram card: {}", exc)


async def _apply_worker(job_id: int, query: Any) -> None:
    """Background worker that submits an approved application."""
    job = get_job_by_id(job_id)
    if not job:
        return

    title = job.get("title", "Role")
    company = job.get("company", "Company")
    url = job.get("url") or ""

    try:
        resume = load_resume()
    except Exception:
        resume = {}

    from core.applicant import JobApplicant
    from core.browser import BrowserManager

    try:
        async with BrowserManager() as browser:
            applicant = JobApplicant(browser, resume)
            applied = await applicant.apply_to_jobs([job], max_apps=1)

            if applied:
                update_job_status(job_id, "applied", notes="Applied via Telegram approval")
                await query.edit_message_text(
                    f"🎉 <b>Application Successfully Submitted!</b>\n\n"
                    f"💼 <b>{title}</b>\n"
                    f"🏢 <b>{company}</b>\n"
                    f"📅 Applied: <b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</b>\n"
                    f"Status: <b>Applied (Recorded in SQLite)</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 View Posting", url=url)]]),
                )
                logger.info("✓ Completed Telegram-triggered application for '{}'", title)
            else:
                # External ATS or manual application needed
                await query.edit_message_text(
                    f"⚠️ <b>Approved — Manual Submission Required</b>\n\n"
                    f"💼 <b>{title}</b> at <b>{company}</b>\n"
                    f"This listing requires external company portal application.\n\n"
                    f"🔗 <a href='{url}'><b>Click here to complete application</b></a>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Complete Application", url=url)]]),
                )
    except Exception as exc:
        logger.error("Telegram apply worker error for '{}': {}", title, exc)
        try:
            await query.edit_message_text(
                f"⚠️ <b>Approval Recorded (Browser Busy)</b>\n\n"
                f"💼 <b>{title}</b> at <b>{company}</b>\n"
                f"Job is marked <b>Approved</b> in your dashboard.\n"
                f"🔗 <a href='{url}'>Apply manually or run <code>python main.py --auto-submit</code></a>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Listing", url=url)]]),
            )
        except Exception:
            pass


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [Approve & Apply] and [Reject] button taps."""
    query = update.callback_query
    if not query or not query.data:
        return

    try:
        await query.answer()
    except Exception:
        pass
    data = query.data

    if data.startswith("approve_"):
        job_id = int(data.split("_")[1])
        job = get_job_by_id(job_id)
        if not job:
            await query.edit_message_text("Job record not found.")
            return

        update_job_status(job_id, "approved", notes="Approved via Telegram button tap")
        title = job.get("title", "Role")
        company = job.get("company", "Company")

        await query.edit_message_text(
            f"⏳ <b>Approved! Starting Application...</b>\n\n"
            f"💼 <b>{title}</b>\n"
            f"🏢 <b>{company}</b>\n"
            f"Status: <b>Approved → Submitting via Playwright...</b>",
            parse_mode="HTML",
        )
        logger.info("Candidate approved job '{}' at '{}' via Telegram", title, company)
        asyncio.create_task(_apply_worker(job_id, query))

    elif data.startswith("reject_"):
        job_id = int(data.split("_")[1])
        job = get_job_by_id(job_id)
        if not job:
            await query.edit_message_text("Job record not found.")
            return

        update_job_status(job_id, "rejected", notes="Rejected via Telegram button tap")
        title = job.get("title", "Role")
        company = job.get("company", "Company")

        await query.edit_message_text(
            f"❌ <b>Job Rejected</b>\n\n"
            f"💼 <b>{title}</b> at <b>{company}</b>\n"
            f"Status: <b>Rejected (Skipped)</b>",
            parse_mode="HTML",
        )
        logger.info("Candidate rejected job '{}' at '{}' via Telegram", title, company)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message and available commands."""
    if not update.effective_message:
        return
    text = (
        "💼 <b>AI Job Application Assistant</b>\n\n"
        "Welcome! Your bot is active and monitoring job listings across LinkedIn & Naukri.\n\n"
        "<b>Available Commands:</b>\n"
        "📊 /status — View live database statistics\n"
        "⏳ /pending — Inspect jobs waiting for your review\n"
        "❓ /help — Quick guide on how approval works\n\n"
        "When high-match jobs (₹12+ LPA) are found, I'll send you an interactive card with "
        "<b>[✅ Approve & Apply]</b> right here!"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return database pipeline metrics."""
    if not update.effective_message:
        return
    m = get_summary_metrics()
    text = (
        "📊 <b>Pipeline Statistics</b>\n\n"
        f"🔍 Total Discovered: <b>{m['total_discovered']}</b>\n"
        f"🌟 High Matches: <b>{m['total_matched']}</b>\n"
        f"⏳ Pending Review: <b>{m['pending_review']}</b>\n"
        f"✅ Approved: <b>{m['approved']}</b>\n"
        f"🚀 Applied: <b>{m['total_applied']}</b>\n"
        f"⛔ Rejected: <b>{m['total_rejected']}</b>\n\n"
        "Use /pending to review waiting jobs."
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send interactive cards for pending review jobs."""
    if not update.effective_message:
        return
    pending = get_pending_review_jobs()
    if not pending:
        await update.effective_message.reply_text(
            "✓ No pending jobs in review queue right now! All matches have been reviewed.",
            parse_mode="HTML",
        )
        return

    await update.effective_message.reply_text(
        f"⏳ Found <b>{len(pending)}</b> jobs pending review. Sending top {min(len(pending), 5)}:",
        parse_mode="HTML",
    )
    for job in pending[:5]:
        await send_interactive_card(job, bot=context.bot)
        await asyncio.sleep(0.4)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message and instructions."""
    if not update.effective_message:
        return
    text = (
        "💡 <b>AI Job Bot Help & Commands</b>\n\n"
        "• <b>/status</b> — Live count of discovered, matched, and applied jobs\n"
        "• <b>/pending</b> — Review high-match jobs awaiting approval\n"
        "• <b>/apply</b> — Automatically submit all pre-approved jobs\n"
        "• <b>/help</b> — Display this instruction card\n\n"
        "<b>How 1-Tap Application Works:</b>\n"
        "1. When high-match listings (₹12+ LPA) are found, the bot pings you here.\n"
        "2. Tap <b>[✅ Approve & Apply]</b> on the card.\n"
        "3. Playwright launches in the background, attaches your resume PDF, submits the application, and alerts you when finished!"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def cmd_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit all approved applications."""
    if not update.effective_message:
        return
    approved = get_jobs_by_status(status="approved")
    if not approved:
        await update.effective_message.reply_text(
            "No pre-approved applications waiting in queue.\n"
            "Use /pending to review matches and click [✅ Approve & Apply].",
            parse_mode="HTML",
        )
        return

    await update.effective_message.reply_text(
        f"🚀 <b>Starting submission for {len(approved)} approved application(s)...</b>",
        parse_mode="HTML",
    )

    try:
        resume = load_resume()
    except Exception:
        resume = {}

    from core.applicant import JobApplicant
    from core.browser import BrowserManager

    async def _batch_submit():
        async with BrowserManager() as browser:
            applicant = JobApplicant(browser, resume)
            applied = await applicant.apply_to_jobs(approved, max_apps=5)
            await update.effective_message.reply_text(
                f"✓ Finished submission run: <b>{len(applied)}</b> jobs successfully applied!",
                parse_mode="HTML",
            )

    asyncio.create_task(_batch_submit())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    from telegram.error import BadRequest, Conflict
    if isinstance(context.error, Conflict):
        logger.warning("Another instance of Telegram bot is already running. Stopping duplicate polling.")
    elif isinstance(context.error, BadRequest) and "query is too old" in str(context.error).lower():
        pass
    else:
        logger.debug("Telegram update error: {}", context.error)


def create_telegram_application() -> Optional[Application]:
    """Create and configure the Telegram Bot Application."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is not set.")
        return None

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("apply", cmd_apply))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_error_handler(error_handler)
    return app
