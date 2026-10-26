"""
core/discovery.py — Responsible Job Discovery & Processing Engine.

Discovers job opportunities across permitted channels:
- Respects site rate limits and terms of service.
- Halts gracefully if CAPTCHA or security verification is encountered (never evades).
- Runs duplicate detection against stable URLs and IDs.
- Applies strict hard filters and transparent multi-factor scoring.
- Enforces Review-Before-Submit mode as default.
- Generates manual application links for every discovered role.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from loguru import logger

import config
from core.db import is_job_duplicate, record_discovered_job
from core.filters import evaluate_hard_filters
from core.profiles import JobProfile, load_profiles
from core.scorer import calculate_transparent_score


class JobDiscoveryEngine:
    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self.profiles: list[JobProfile] = load_profiles()

    async def process_job(
        self,
        raw_job: dict[str, Any],
        profile: JobProfile,
        resume: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Runs the full vetting pipeline for a single discovered job:
        1. Duplicate check
        2. Hard filters
        3. Transparent scoring
        4. Storage into SQLite
        """
        source = raw_job.get("source", "linkedin")
        job_id = str(raw_job.get("job_id", "")).strip()
        url = raw_job.get("url", "")
        title = raw_job.get("title", "Unknown Role")
        company = raw_job.get("company", "Unknown Company")

        # 1. Deduplication Check
        if is_job_duplicate(source, job_id, url):
            logger.debug("Duplicate job skipped: {} at {} ({})", title, company, url)
            return {"status": "duplicate", "job_id": job_id, "title": title}

        # 2. Hard Filters Check
        filter_passed, filter_reason, _ = evaluate_hard_filters(raw_job, profile)
        if not filter_passed:
            row_id, _ = record_discovered_job(
                job=raw_job,
                profile_id=profile.id,
                profile_name=profile.name,
                hard_filter_passed=False,
                rejection_reason=filter_reason,
                default_status="rejected",
            )
            logger.info("⛔ Rejected by Hard Filter: '{}' at '{}' — {}", title, company, filter_reason)
            return {
                "status": "rejected_filter",
                "job_id": job_id,
                "title": title,
                "reason": filter_reason,
                "db_id": row_id,
            }

        # 3. Transparent Match Scoring
        score_breakdown = await calculate_transparent_score(raw_job, profile, resume)
        total_score = score_breakdown.total_score

        # 4. Score Threshold Check
        if total_score < profile.min_match_score:
            rejection_note = f"Match score ({total_score}) below profile minimum ({profile.min_match_score})"
            row_id, _ = record_discovered_job(
                job=raw_job,
                profile_id=profile.id,
                profile_name=profile.name,
                hard_filter_passed=True,
                rejection_reason=rejection_note,
                score_breakdown=score_breakdown.to_dict(),
                default_status="rejected",
            )
            logger.info("📉 Below Threshold: '{}' at '{}' — Score: {}/100 (Min: {})", title, company, total_score, profile.min_match_score)
            return {
                "status": "rejected_score",
                "job_id": job_id,
                "title": title,
                "score": total_score,
                "reason": rejection_note,
                "db_id": row_id,
            }

        # 5. Passed Vetting -> Review-Before-Submit Queue
        row_id, is_new = record_discovered_job(
            job=raw_job,
            profile_id=profile.id,
            profile_name=profile.name,
            hard_filter_passed=True,
            rejection_reason="",
            score_breakdown=score_breakdown.to_dict(),
            default_status="review_pending",
        )

        logger.info(
            "🌟 MATCH FOUND [{}]: '{}' at '{}' — Score: {}/100 (Review Pending)",
            profile.name,
            title,
            company,
            total_score,
        )

        return {
            "status": "matched",
            "job_id": job_id,
            "title": title,
            "company": company,
            "score": total_score,
            "breakdown": score_breakdown.to_dict(),
            "manual_apply_url": raw_job.get("url"),
            "db_id": row_id,
        }

    async def run_discovery_for_profile(
        self,
        profile: JobProfile,
        resume: dict[str, Any],
        browser_manager: Optional[Any] = None,
        limit_per_search: int = 15,
    ) -> list[dict[str, Any]]:
        """
        Discovers and processes jobs for a specific profile.
        """
        logger.info("🔍 Starting Discovery for Profile: '{}'", profile.name)
        discovered_jobs: list[dict[str, Any]] = []

        if browser_manager is None:
            logger.info("Offline / standalone mode: no browser instance supplied.")
            return discovered_jobs

        from scrapers.linkedin import LinkedInScraper

        # Temporarily adapt scraper preferences to profile
        profile_resume = dict(resume)
        profile_resume["job_preferences"] = {
            "titles": profile.target_titles,
            "locations": profile.preferred_locations,
            "blacklist_companies": profile.blacklist_companies,
            "blacklist_keywords": profile.blacklist_keywords,
            "min_ai_match_score": profile.min_match_score,
        }

        try:
            scraper = LinkedInScraper(browser_manager, profile_resume)
            LinkedInScraper.MAX_TOTAL_JOBS = limit_per_search  # type: ignore[attr-defined]

            raw_jobs = await scraper.scrape()
            logger.info("Found {} raw listings for '{}'", len(raw_jobs), profile.name)

            for raw in raw_jobs:
                res = await self.process_job(raw, profile, resume)
                discovered_jobs.append(res)
                await asyncio.sleep(0.2)

        except Exception as exc:
            logger.error("Discovery error for profile '{}': {}", profile.name, exc)

        return discovered_jobs
