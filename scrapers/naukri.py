"""
scrapers/naukri.py — Naukri.com job search scraper (Internships only, last 2 days).

Navigates to Naukri search results, paginates through listings, and
extracts internship job card data posted within the last 2 days.
Login session is maintained via the persistent browser context.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

from loguru import logger
from playwright.async_api import Page, TimeoutError as PwTimeout

from core.browser import (
    BrowserManager,
    SessionExpiredError,
    human_delay,
    random_scroll,
)
from scrapers.base_scraper import BaseScraper


class NaukriScraper(BaseScraper):
    SOURCE = "naukri"

    def __init__(self, browser: BrowserManager, resume: dict[str, Any]) -> None:
        super().__init__(browser, resume)

    # ──────────────────────────────────────────────────────────────
    #  Session check
    # ──────────────────────────────────────────────────────────────
    async def check_session(self, page: Page) -> bool:
        """Navigate to Naukri and verify the user is logged in."""
        await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded", timeout=30_000)
        await human_delay(2, 4)

        if not self._is_login_page(page.url):
            return True

        logger.info("👉 Not logged in to Naukri. Please log in now in the browser window.")
        logger.info("   (Use Google, email/password, or any method you prefer)")
        logger.info("   Waiting up to 5 minutes for login to complete...")

        import time
        deadline = time.time() + 300
        while time.time() < deadline:
            await human_delay(2, 3)
            try:
                current_url = page.url
                if not self._is_login_page(current_url):
                    logger.info("✓ Naukri login detected (URL: {})! Continuing...", current_url[:60])
                    await human_delay(2, 4)
                    return True

                logged_in = await page.locator(
                    ".nI-gNb-drawer, .nI-gNb-header__usermenu, "
                    ".nI-gNb-sb__main, .user-info, img.nI-gNb-header__userImg"
                ).count()
                if logged_in > 0:
                    logger.info("✓ Naukri login detected (nav elements found)! Continuing...")
                    await human_delay(2, 4)
                    return True
            except Exception:
                continue

        logger.error("Login timed out after 5 minutes.")
        return False

    @staticmethod
    def _is_login_page(url: str) -> bool:
        """Return True if the URL looks like a Naukri login page."""
        return "/nlogin" in url or "login" in url.lower()

    # ──────────────────────────────────────────────────────────────
    #  Build search URL — internship, last 2 days
    # ──────────────────────────────────────────────────────────────
    def _build_search_url(self, keywords: str, location: str, page_num: int = 1) -> str:
        """
        Build Naukri search URL for fresher / 0–1 year roles.

        Filters:
        - experience=0 (fresher / entry-level)
        - jobAge=7 (posted within last 7 days)
        - sortBy=date (most recent first)
        """
        kw_slug = keywords.lower().replace(" ", "-")
        loc_slug = location.lower().replace(" ", "-").replace(",", "")
        return (
            f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"
            f"?k={quote_plus(keywords)}&l={quote_plus(location)}"
            f"&experience=0"
            f"&jobAge=7"
            f"&nignbevent_src=jobsearchDeskGNB"
            f"&sortBy=date"
            + (f"&pageNo={page_num}" if page_num > 1 else "")
        )

    # ──────────────────────────────────────────────────────────────
    #  Extract job cards
    # ──────────────────────────────────────────────────────────────
    async def _extract_jobs(self, page: Page) -> list[dict[str, Any]]:
        """Parse job cards from a Naukri search results page."""
        jobs: list[dict[str, Any]] = []
        cards = page.locator("article.jobTuple, .srp-jobtuple-wrapper, .cust-job-tuple")
        count = await cards.count()

        if count == 0:
            # Naukri v2 layout
            cards = page.locator("[data-job-id], .styles_jlc__main__VdwtF")
            count = await cards.count()

        for i in range(count):
            try:
                card = cards.nth(i)

                # Title
                title_el = card.locator("a.title, a[class*='title'], .row1 a, .info h2 a")
                title = (await title_el.first.inner_text()).strip() if await title_el.count() > 0 else ""

                # Company
                company_el = card.locator("a.subTitle, .comp-name, a[class*='comp'], .row2 span a")
                company = (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else ""

                # Location
                loc_el = card.locator(".locWdth, .loc-wrap, span[class*='loc'], .row3 .loc span")
                location = (await loc_el.first.inner_text()).strip() if await loc_el.count() > 0 else ""

                # URL and Job ID
                link_el = card.locator("a.title, a[class*='title'], .row1 a, .info h2 a")
                href = await link_el.first.get_attribute("href") if await link_el.count() > 0 else ""

                job_id_match = re.search(r"-(\d{10,})\??", href or "")
                if not job_id_match:
                    job_id_attr = await card.get_attribute("data-job-id") or await card.get_attribute("id") or ""
                    job_id = job_id_attr or f"naukri_unknown_{i}"
                else:
                    job_id = job_id_match.group(1)

                url = href or ""
                if url and not url.startswith("http"):
                    url = f"https://www.naukri.com{url}"

                # Easy apply detection
                apply_btn = card.locator("button:has-text('Apply'), .apply-btn, [class*='apply']")
                easy_apply = await apply_btn.count() > 0

                jobs.append({
                    "source": self.SOURCE,
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "easy_apply": easy_apply,
                    "description": None,
                })
            except Exception as exc:
                logger.warning("Failed to parse Naukri card {}: {}", i, exc)
                continue

        logger.info("Extracted {} jobs from Naukri page", len(jobs))
        return jobs

    # ──────────────────────────────────────────────────────────────
    #  Main scrape flow
    # ──────────────────────────────────────────────────────────────
    async def scrape(self) -> list[dict[str, Any]]:
        page = await self.browser.new_page()

        try:
            # 1. Session check
            if not await self.check_session(page):
                raise SessionExpiredError(
                    "Naukri session expired — please log in manually in the persistent browser."
                )

            all_jobs: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            titles = self.preferences.get("titles", ["Software Engineer Intern"])
            locations = self.preferences.get("locations", ["Remote"])
            total_combos = len(titles) * len(locations)
            combo_idx = 0

            for title in titles:
                for loc in locations:
                    combo_idx += 1
                    max_pages = 1  # 2-day window won't fill a second page
                    for page_num in range(1, max_pages + 1):
                        url = self._build_search_url(title, loc, page_num)
                        logger.info("[Naukri {}/{}] '{}' in '{}' — page {}", combo_idx, total_combos, title, loc, page_num)
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                            await human_delay(1, 2)
                        except Exception as exc:
                            logger.warning("Failed to load Naukri search: {}", exc)
                            continue

                        # Scroll to load lazy cards
                        for _ in range(2):
                            await random_scroll(page, 300, 600)

                        jobs = await self._extract_jobs(page)
                        if not jobs:
                            logger.info("No more results — stopping pagination")
                            break

                        new_count = 0
                        for job in jobs:
                            if job["job_id"] not in seen_ids:
                                seen_ids.add(job["job_id"])
                                all_jobs.append(job)
                                new_count += 1
                        if new_count > 0:
                            logger.info("  +{} new Naukri jobs (total: {})", new_count, len(all_jobs))
                        await human_delay(2, 4)

            logger.info("Naukri scrape complete — {} unique intern jobs collected", len(all_jobs))
            return all_jobs

        finally:
            await page.close()
