"""
main.py — Free AI Job Application Agent.

Features:
- 3 configurable job profiles (Full Stack, Data/ML, DevOps/Cloud)
- Permitted job discovery with rate-limiting and human-jitter pauses
- Anti-bot / CAPTCHA compliance: halts gracefully on challenges (never bypasses)
- Hard constraints vetting (Salary, Location, Eligibility, Skills, Experience)
- Stable URL & ID duplicate detection in local SQLite
- Transparent multi-factor match score (0-100) with explainable dimensions
- Free AI support: Local Ollama (Ollama models) + Free Gemini Quota + 100% Free Local Deterministic Matcher
- Review-Before-Submit mode as default
- Direct manual application links for external & ATS postings
- Dry-run mode for zero-risk discovery and inspection

Usage:
  # 1. Discover jobs in safe dry-run mode (default Review-Before-Submit)
  python main.py --profile profile_1 --dry-run

  # 2. Discover for all 3 profiles
  python main.py --profile all --dry-run

  # 3. Launch the Streamlit Review Dashboard
  python -m streamlit run dashboard.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

import config
from config import load_resume
from core.applicant import JobApplicant
from core.browser import BrowserManager, SessionExpiredError
from core.db import get_summary_metrics, init_db, record_discovered_job
from core.discovery import JobDiscoveryEngine
from core.filters import evaluate_hard_filters
from core.profiles import JobProfile, get_profile, load_profiles
from core.scorer import calculate_transparent_score
from notifier import send_telegram_results

logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level:8s}</level> | {message}",
)
logger.add(
    config.BASE_DIR / "bot.log",
    level="DEBUG",
    rotation="5 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:8s} | {name}:{function}:{line} | {message}",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Free AI Job Application Agent — Review-Before-Submit Job Hunter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="all",
        help="Target job profile: 'profile_1', 'profile_2', 'profile_3', or 'all' (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Search, filter, score, and queue jobs in SQLite without submitting (Default: True)",
    )
    parser.add_argument(
        "--auto-submit",
        action="store_true",
        default=False,
        help="Explicitly enable automatic submission for approved Easy Apply jobs (Disabled by default)",
    )
    parser.add_argument(
        "--sites",
        choices=["linkedin", "naukri", "web", "all"],
        default="all",
        help="Job listing sources to search (default: all — LinkedIn, Naukri, and Web)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max listings to discover per profile/site (default: 20)",
    )
    parser.add_argument(
        "--max-apply",
        type=int,
        default=None,
        help="Safety cap on applications per session (default: from .env)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="Override minimum transparent match score threshold (0-100)",
    )
    parser.add_argument(
        "--saved",
        action="store_true",
        help="Review and apply to LinkedIn bookmarked/saved jobs",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the interactive Streamlit review dashboard",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        default=False,
        help="Run continuous automated discovery in the background at periodic intervals",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Interval in minutes between discovery runs in --watch mode (default: 60)",
    )
    parser.add_argument(
        "--telegram-bot",
        action="store_true",
        default=False,
        help="Run the interactive Telegram bot polling listener for mobile approvals",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        default=False,
        help="Open Chromium browser to log in to LinkedIn & Naukri and persist session cookies",
    )
    return parser.parse_args()


async def run_discovery_pipeline(args: argparse.Namespace) -> None:
    init_db()

    # Load candidate resume base
    try:
        resume = load_resume()
    except Exception as exc:
        logger.warning("Could not load resume.json ({}). Using resume.example.json template.", exc)
        example_path = config.BASE_DIR / "resume.example.json"
        with open(example_path, "r", encoding="utf-8") as f:
            resume = json.load(f)

    # Resolve profiles to process
    all_profiles = load_profiles()
    if args.profile.lower() == "all":
        target_profiles = all_profiles
    else:
        p = get_profile(args.profile)
        target_profiles = [p] if p else all_profiles

    logger.info("═" * 60)
    logger.info("💼 Free AI Job Application Agent")
    logger.info(
        "Mode: {} | Profiles: {} | Sites: {}",
        "DRY RUN (Review-Before-Submit)" if args.dry_run or not args.auto_submit else "AUTO-SUBMIT ENABLED",
        ", ".join([p.name for p in target_profiles]),
        args.sites,
    )
    logger.info("═" * 60)

    discovery_engine = JobDiscoveryEngine(dry_run=args.dry_run)
    max_apps = args.max_apply or config.MAX_APPLICATIONS_PER_RUN

    all_matched: list[dict[str, Any]] = []
    all_rejected: list[dict[str, Any]] = []
    all_applied: list[dict[str, Any]] = []

    # Check if browser interaction is needed
    async with BrowserManager() as browser:
        for profile in target_profiles:
            if args.min_score:
                profile.min_match_score = args.min_score

            logger.info("🔍 Processing Profile: {} (Min Score: {})", profile.name, profile.min_match_score)
            results = await discovery_engine.run_discovery_for_profile(
                profile=profile,
                resume=resume,
                browser_manager=browser,
                limit_per_search=args.limit,
                sites=args.sites,
            )
            matched_for_profile = [r for r in results if r.get("status") == "matched"]
            rejected_for_profile = [r for r in results if r.get("status") in ("rejected_filter", "rejected_score")]
            all_matched.extend(matched_for_profile)
            all_rejected.extend(rejected_for_profile)

            logger.info("✓ Profile '{}': {} matched opportunities queued for review", profile.name, len(matched_for_profile))

        # If user explicitly opted into --auto-submit (not dry-run)
        if args.auto_submit and not args.dry_run:
            from core.db import get_jobs_by_status
            approved_jobs = get_jobs_by_status(status="approved")
            if approved_jobs:
                logger.info("═══ Submitting Approved Applications (Cap: {}) ═══", max_apps)
                applicant = JobApplicant(browser, resume)
                all_applied = await applicant.apply_to_jobs(approved_jobs, max_apps=max_apps)
                logger.info("✓ Successfully applied to {} approved jobs", len(all_applied))
            else:
                logger.info("No pre-approved jobs in queue. Review matched jobs on dashboard first.")

    # Send Telegram notification if configured
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            logger.info("📱 Sending Telegram discovery summary...")
            await send_telegram_results(
                passed_jobs=all_matched,
                failed_jobs=all_rejected,
                results_file=config.BASE_DIR / "bot.log",
                applied=all_applied,
            )
        except Exception as exc:
            logger.warning("Telegram notification encountered error: {}", exc)

    metrics = get_summary_metrics()
    logger.info("═" * 60)
    logger.info("📊 Pipeline Summary:")
    logger.info("   Total Discovered: {}", metrics["total_discovered"])
    logger.info("   Matched Roles:    {}", metrics["total_matched"])
    logger.info("   Pending Review:   {}", metrics["pending_review"])
    logger.info("   Approved:         {}", metrics["approved"])
    logger.info("   Total Applied:    {}", metrics["total_applied"])
    logger.info("   Total Rejected:   {}", metrics["total_rejected"])
    logger.info("═" * 60)
    logger.info("💡 Next Step: Open the dashboard to inspect match scores & approve applications:")
    logger.info("   python -m streamlit run dashboard.py")


def main() -> None:
    args = parse_args()

    if args.login:
        from scripts.login import interactive_login
        asyncio.run(interactive_login())
        return

    if args.dashboard:
        logger.info("Launching Streamlit dashboard...")
        subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py"])
        return

    if args.telegram_bot:
        logger.info("🤖 Starting Telegram Interactive Bot Listener...")
        from core.telegram_bot import create_telegram_application
        app = create_telegram_application()
        if app:
            logger.info("✓ Telegram Bot active! Listening for commands (/status, /pending) and [Approve & Apply] taps...")
            app.run_polling()
        else:
            logger.error("Could not initialize Telegram bot. Ensure TELEGRAM_BOT_TOKEN is set in .env")
        return

    if args.watch:
        logger.info("🕒 Continuous Watch Mode activated (Interval: {} minutes).", args.interval)

        async def _run_watch():
            from core.telegram_bot import create_telegram_application
            app = create_telegram_application()

            async def _discovery_loop():
                while True:
                    try:
                        logger.info("═══ Starting Discovery Cycle: {} ═══", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        await run_discovery_pipeline(args)
                    except Exception as exc:
                        logger.error("Error during watch discovery cycle: {}", exc)
                    logger.info("Cycle finished. Next discovery cycle in {} minutes.", args.interval)
                    await asyncio.sleep(args.interval * 60)

            if app and config.TELEGRAM_BOT_TOKEN:
                async with app:
                    await app.start()
                    await app.updater.start_polling()
                    logger.info("✓ Interactive Telegram Bot running concurrently in watch mode.")
                    await _discovery_loop()
            else:
                await _discovery_loop()

        asyncio.run(_run_watch())
        return

    asyncio.run(run_discovery_pipeline(args))


if __name__ == "__main__":
    main()
