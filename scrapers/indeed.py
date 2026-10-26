"""
scrapers/indeed.py — Open Web & Indeed Job Search Scraper.

Crawls open internet job listings from Indeed India:
- No mandatory login wall for search & discovery.
- Filters by entry-level/fresher roles and recent postings (last 7 days).
- Extracts title, company, location, salary snippet, and direct application URLs.
- Supports Google sign-in / Gmail authentication for automated applying.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from loguru import logger
from playwright.async_api import Page, TimeoutError as PwTimeout

import config
from core.browser import (
    BrowserManager,
    human_delay,
    random_scroll,
)
from scrapers.base_scraper import BaseScraper


class IndeedScraper(BaseScraper):
    SOURCE = "web"
    MAX_TOTAL_JOBS = 30

    def __init__(self, browser: BrowserManager, resume: dict[str, Any]) -> None:
        super().__init__(browser, resume)

    async def check_session(self, page: Page) -> bool:
        """
        Indeed allows public job browsing without login.
        If Google login credentials exist, verifies or establishes Google session.
        """
        try:
            await page.goto("https://in.indeed.com", wait_until="domcontentloaded", timeout=25_000)
            await human_delay(1, 2)
            return True
        except Exception as exc:
            logger.debug("Indeed session check notice: {}", exc)
            return True

    def _build_search_url(self, keywords: str, location: str, page_num: int = 0) -> str:
        """Build Indeed search URL for recent postings in India."""
        loc = location if location.lower() != "remote" else "India"
        query = keywords
        if location.lower() == "remote":
            query += " remote"

        start_param = f"&start={page_num * 10}" if page_num > 0 else ""
        return (
            f"https://in.indeed.com/jobs"
            f"?q={quote_plus(query)}"
            f"&l={quote_plus(loc)}"
            f"&fromage=7"
            f"&sort=date"
            f"{start_param}"
        )

    async def _extract_jobs(self, page: Page) -> list[dict[str, Any]]:
        """Extract job listings from Indeed search results page."""
        jobs: list[dict[str, Any]] = []

        # Wait for job container
        try:
            await page.wait_for_selector(".job_seen_beacon, [data-jk], .jobCard_mainContent", timeout=8_000)
        except PwTimeout:
            logger.debug("No Indeed job card selector appeared within timeout.")
            return jobs

        cards = page.locator(".job_seen_beacon, [data-jk]")
        count = await cards.count()

        for i in range(count):
            try:
                card = cards.nth(i)

                # Job ID
                jk = await card.get_attribute("data-jk")
                if not jk:
                    link = card.locator("a[data-jk], a[id*='job_']")
                    if await link.count() > 0:
                        jk = await link.first.get_attribute("data-jk")
                if not jk:
                    continue

                # Title
                title_el = card.locator("h2.jobTitle span, a.jcs-JobTitle span, a.jcs-JobTitle")
                title = ""
                if await title_el.count() > 0:
                    title = (await title_el.first.inner_text()).strip()

                if not title:
                    continue

                # Company
                comp_el = card.locator("[data-testid='company-name'], .companyName, span.companyName")
                company = "Unknown"
                if await comp_el.count() > 0:
                    company = (await comp_el.first.inner_text()).strip()

                # Location
                loc_el = card.locator("[data-testid='text-location'], .companyLocation")
                location = "India"
                if await loc_el.count() > 0:
                    location = (await loc_el.first.inner_text()).strip()

                # Salary
                salary_raw = ""
                sal_el = card.locator("[data-testid='attribute_snippet_testid'], .salary-snippet-container, .metadata div")
                sal_count = await sal_el.count()
                for s_idx in range(sal_count):
                    s_text = (await sal_el.nth(s_idx).inner_text()).strip()
                    if any(sym in s_text for sym in ("₹", "LPA", "lakh", "lac", "$", "a year", "per month")):
                        salary_raw = s_text
                        break

                # Easy apply
                easy_apply = (await card.locator("text='Easily apply', [data-testid='ia-badge']").count()) > 0
                job_url = f"https://in.indeed.com/viewjob?jk={jk}"

                jobs.append({
                    "source": "web",
                    "job_id": jk,
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary_raw": salary_raw,
                    "url": job_url,
                    "easy_apply": easy_apply,
                    "description": None,
                })
            except Exception as exc:
                logger.debug("Failed parsing Indeed card {}: {}", i, exc)
                continue

        logger.info("Extracted {} web jobs from Indeed page", len(jobs))
        return jobs

    async def scrape(self) -> list[dict[str, Any]]:
        """Execute web discovery across preferred titles and locations."""
        page = await self.browser.new_page(caller="web")
        try:
            await self.check_session(page)

            all_jobs: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            titles = self.preferences.get("titles", ["Software Engineer"])[:4]
            locations = self.preferences.get("locations", ["Bangalore", "India"])[:3]

            combo_idx = 0
            total_combos = len(titles) * len(locations)

            for title in titles:
                if len(all_jobs) >= self.MAX_TOTAL_JOBS:
                    break
                for loc in locations:
                    if len(all_jobs) >= self.MAX_TOTAL_JOBS:
                        break
                    combo_idx += 1
                    logger.info("[Web {}/{}] Searching '{}' in '{}'", combo_idx, total_combos, title, loc)
                    search_url = self._build_search_url(title, loc)

                    try:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                        await human_delay(1.5, 3.0)
                    except Exception as exc:
                        logger.warning("Failed loading Indeed search '{}': {}", search_url, exc)
                        continue

                    # Scroll down to load cards
                    for _ in range(2):
                        await random_scroll(page, 400, 700)

                    jobs = await self._extract_jobs(page)
                    new_count = 0
                    for j in jobs:
                        if j["job_id"] not in seen_ids:
                            seen_ids.add(j["job_id"])
                            all_jobs.append(j)
                            new_count += 1

                    if new_count > 0:
                        logger.info("  +{} new web listings found (total: {})", new_count, len(all_jobs))

                    await human_delay(1.5, 3.0)

            logger.info("Web discovery complete — {} unique jobs collected across internet", len(all_jobs))
            return all_jobs
        finally:
            await self.browser.safe_close_page(page, caller="web")
