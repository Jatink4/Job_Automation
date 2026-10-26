"""
scrapers/linkedin.py — LinkedIn job search scraper.

Navigates to LinkedIn Jobs, applies search filters derived from
``resume.json → job_preferences``, scrolls infinite-scroll panels,
and extracts job card data.

IMPORTANT:  The first run must be done with the browser visible so
you can log in manually.  The persistent browser context will keep
your session for subsequent runs.
"""

from __future__ import annotations

import re
import asyncio
from typing import Any
from urllib.parse import quote_plus

from loguru import logger
from playwright.async_api import Page, TimeoutError as PwTimeout

from core.browser import (
    BrowserManager,
    SessionExpiredError,
    human_delay,
    random_scroll,
    take_screenshot,
)
from scrapers.base_scraper import BaseScraper


class LinkedInScraper(BaseScraper):
    SOURCE = "linkedin"
    MAX_TOTAL_JOBS = 40

    def __init__(self, browser: BrowserManager, resume: dict[str, Any]) -> None:
        super().__init__(browser, resume)

    # ──────────────────────────────────────────────────────────────
    #  Main scrape flow
    # ──────────────────────────────────────────────────────────────
    # LinkedIn shows 25 results per page
    JOBS_PER_PAGE = 25
    MAX_PAGES_PER_SEARCH = 1  # 1 page per combo (last 3 days won't have many results)

    async def scrape_saved(self) -> list[dict[str, Any]]:
        """Collect jobs from LinkedIn Jobs → My Jobs → Saved via UI clicks."""
        page = await self.browser.get_page()
        if not await self.check_session(page):
            raise SessionExpiredError(
                "LinkedIn session expired — please log in manually in the persistent browser."
            )

        # Navigate through UI — direct saved-jobs URL often redirects bots to feed
        await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=45_000)
        await human_delay(2, 4)
        logger.info("On Jobs hub: {}", page.url[:100])

        opened = False
        for sel in (
            "a:has-text('My jobs')",
            "a:has-text('My Jobs')",
            "a:has-text('Job tracker')",
            "a[href*='my-items/saved-jobs']",
            "a[href*='/jobs/collections/saved']",
        ):
            loc = page.locator(sel)
            if await loc.count() == 0:
                continue
            try:
                await loc.first.click(timeout=4000)
                await human_delay(2, 4)
                opened = True
                logger.info("Clicked My Jobs control ({})", sel)
                break
            except Exception:
                continue

        if not opened:
            await page.goto(
                "https://www.linkedin.com/my-items/saved-jobs/",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            await human_delay(3, 5)

        try:
            tab = page.get_by_role("tab", name=re.compile(r"^Saved$", re.I))
            if await tab.count() > 0:
                await tab.first.click(timeout=4000)
                await human_delay(2, 3)
                logger.info("Clicked Saved tab")
        except Exception as exc:
            logger.debug("Saved tab: {}", exc)

        logger.info("Saved-jobs URL: {}", page.url[:120])
        logger.info("Waiting for saved job cards…")
        ready_links = 0
        for attempt in range(50):
            ready_links = await page.locator("a[href*='/jobs/view/']").count()
            cards = await page.locator(
                ".entity-result, li.reusable-search__result-container, "
                "[data-chameleon-result-urn], .job-card-container, "
                ".scaffold-finite-scroll__content li"
            ).count()
            if ready_links > 0 or (cards > 0 and attempt > 5):
                await human_delay(2, 3)
                ready_links = await page.locator("a[href*='/jobs/view/']").count()
                break
            if attempt in (10, 20, 30):
                await page.keyboard.press("End")
            await page.evaluate("window.scrollBy(0, 600)")
            await human_delay(1.0, 1.4)

        logger.info("Saved jobs page ready — {} job links", ready_links)
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, 1200)")
            await human_delay(0.5, 0.9)

        raw = await page.evaluate(
            r"""() => {
                const out = [];
                const seen = new Set();
                const add = (jobId, title, company) => {
                    if (!jobId || seen.has(jobId)) return;
                    seen.add(jobId);
                    out.push({
                        job_id: jobId,
                        title: (title || 'Saved job').trim().split('\n')[0],
                        company: (company || 'Unknown').trim().split('\n')[0],
                        url: 'https://www.linkedin.com/jobs/view/' + jobId + '/',
                    });
                };
                for (const a of document.querySelectorAll('a[href*="/jobs/view/"]')) {
                    const m = a.href.match(/\/jobs\/view\/(\d+)/);
                    if (!m) continue;
                    const row = a.closest('li, .entity-result, .job-card-container, article, div');
                    let company = '';
                    if (row) {
                        const c = row.querySelector(
                          '.entity-result__primary-subtitle, .job-card-container__primary-description, .artdeco-entity-lockup__subtitle'
                        );
                        if (c) company = c.innerText || '';
                    }
                    add(m[1], a.innerText || a.getAttribute('aria-label') || '', company);
                }
                for (const el of document.querySelectorAll('[data-chameleon-result-urn], [data-entity-urn], [data-job-id]')) {
                    const urn = el.getAttribute('data-chameleon-result-urn')
                      || el.getAttribute('data-entity-urn')
                      || el.getAttribute('data-job-id')
                      || '';
                    const m = String(urn).match(/(\d{8,})/);
                    if (!m) continue;
                    const titleEl = el.querySelector('a, .entity-result__title-text, .job-card-list__title, span');
                    const title = titleEl ? titleEl.innerText : '';
                    const c = el.querySelector('.entity-result__primary-subtitle, .artdeco-entity-lockup__subtitle');
                    add(m[1], title, c ? c.innerText : '');
                }
                return out;
            }"""
        )

        jobs: list[dict[str, Any]] = []
        for item in raw or []:
            jobs.append(
                {
                    "source": self.SOURCE,
                    "job_id": str(item["job_id"]),
                    "title": item.get("title") or "Saved job",
                    "company": item.get("company") or "Unknown",
                    "location": "",
                    "url": item["url"],
                    "easy_apply": True,
                    "description": None,
                    "from_saved": True,
                    "ai_score": 100,
                }
            )

        if not jobs:
            try:
                await take_screenshot(page, "saved_jobs_empty")
            except Exception as exc:
                logger.warning("Screenshot failed: {}", exc)
            try:
                snippet = (await page.inner_text("body"))[:500].replace("\n", " ")
                logger.info("Saved page text sample: {}", snippet)
            except Exception:
                pass

        logger.info("Collected {} saved LinkedIn jobs", len(jobs))
        return jobs

    async def scrape(self) -> list[dict[str, Any]]:
        """Run the full scraping flow for LinkedIn — prioritize Easy Apply jobs first."""
        page = await self.browser.get_page()
        try:
            if not await self.check_session(page):
                raise SessionExpiredError(
                    "LinkedIn session expired — please log in manually in the persistent browser."
                )

            all_jobs: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            titles = self.preferences.get("titles", ["Software Engineer"])[:6]
            locations = self.preferences.get("locations", ["Remote"])[:5]
            total_combos = len(titles) * len(locations)
            combo_idx = 0

            for title in titles:
                if len(all_jobs) >= self.MAX_TOTAL_JOBS:
                    break
                for loc in locations:
                    if len(all_jobs) >= self.MAX_TOTAL_JOBS:
                        break
                    combo_idx += 1
                    logger.info("[EasyApply {}/{}] '{}' in '{}'", combo_idx, total_combos, title, loc)
                    url = self._build_search_url(title, loc, easy_apply=True)
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        await human_delay(1, 2)
                    except Exception as exc:
                        logger.warning("Failed to load Easy Apply search: {}", exc)
                        continue
                    await self._scroll_job_list(page)
                    jobs = await self._extract_jobs(page)
                    new_count = 0
                    for job in jobs:
                        if job["job_id"] not in seen_ids:
                            seen_ids.add(job["job_id"])
                            job["easy_apply"] = True
                            all_jobs.append(job)
                            new_count += 1
                    if new_count > 0:
                        logger.info("  +{} new Easy Apply jobs (total: {})", new_count, len(all_jobs))
                    await human_delay(1, 3)

            logger.info("LinkedIn scrape complete — {} Easy Apply jobs from {} combos", len(all_jobs), total_combos)
            return all_jobs
        finally:
            pass

    # ──────────────────────────────────────────────────────────────
    #  Session check
    # ──────────────────────────────────────────────────────────────
    async def check_session(self, page: Page) -> bool:
        """Navigate to LinkedIn and verify we're logged in.
        If not logged in, wait for the user to complete manual login
        (Google Sign-In, email/password, or any other method)."""
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30_000)
        await human_delay(2, 4)

        # Check if already logged in (redirected to feed/jobs)
        if not self._is_login_page(page.url):
            return True

        logger.info("👉 Not logged in to LinkedIn. Please log in now in the browser window.")
        logger.info("   (Use 'Sign in with Google', email/password, or any method you prefer)")
        logger.info("   Waiting up to 5 minutes for login to complete...")

        # Poll every 3 seconds — check both URL change and page elements
        import time
        deadline = time.time() + 300  # 5 minutes
        while time.time() < deadline:
            await human_delay(2, 3)
            try:
                current_url = page.url
                # Check if URL moved away from login pages
                if not self._is_login_page(current_url):
                    logger.info("✓ LinkedIn login detected (URL: {})! Continuing...", current_url[:60])
                    await human_delay(2, 4)
                    return True

                # Also check if logged-in elements appeared on the page
                # (handles cases where URL doesn't change immediately)
                logged_in = await page.locator(
                    ".global-nav, .feed-identity-module, img.global-nav__me-photo, "
                    ".search-global-typeahead, [data-control-name='nav.homepage']"
                ).count()
                if logged_in > 0:
                    logger.info("✓ LinkedIn login detected (nav elements found)! Continuing...")
                    await human_delay(2, 4)
                    return True
            except Exception:
                # Page might be navigating, ignore transient errors
                continue

        logger.error("Login timed out after 5 minutes.")
        return False

    @staticmethod
    def _is_login_page(url: str) -> bool:
        """Return True if the URL looks like a LinkedIn login/auth page."""
        login_indicators = ["/login", "/authwall", "/uas/", "/checkpoint/"]
        return any(ind in url for ind in login_indicators)

    # ──────────────────────────────────────────────────────────────
    #  Build search URL
    # ──────────────────────────────────────────────────────────────
    def _build_search_url(self, title: str, location: str, start: int = 0, easy_apply: bool = False) -> str:
        """
        Construct a LinkedIn job search URL with filters.

        f_TPR=r604800 → date posted: past 7 days
        f_AL=true     → Easy Apply only
        geoId         → bias to India when location is an Indian city / Remote
        """
        keywords = quote_plus(title)
        loc = quote_plus(location)
        # India geo — keeps results from drifting to UK public listings
        india_geo = "102713980"
        url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={keywords}&location={loc}"
            f"&geoId={india_geo}"
            f"&f_TPR=r604800"
            f"&sortBy=DD"
        )
        if easy_apply:
            url += "&f_AL=true"
        if start > 0:
            url += f"&start={start}"
        return url

    # ──────────────────────────────────────────────────────────────
    #  Scroll job list panel until no new cards appear
    # ──────────────────────────────────────────────────────────────
    async def _scroll_job_list(self, page: Page, max_scrolls: int = 10) -> None:
        """Scroll the left-hand job list container to load all results."""
        # Try multiple selectors — prefer logged-in selectors
        card_selectors = [
            "[data-job-id]",
            "li[data-job-id]",
            ".job-card-container",
            ".jobs-search-results__list-item",
        ]
        
        # Find which selector works
        working_selector = None
        for sel in card_selectors:
            count = await page.locator(sel).count()
            if count > 0:
                working_selector = sel
                logger.info("Using selector '{}' (found {} cards)", sel, count)
                break
        
        if not working_selector:
            logger.warning("No job card selectors found any cards")
            return
        
        prev_count = 0
        for i in range(max_scrolls):
            cards = await page.locator(working_selector).count()
            if cards == prev_count and i > 2:
                logger.info("No new cards after scroll {} (total {})", i, cards)
                break
            prev_count = cards

            # Scroll the panel (not the window)
            await page.evaluate(
                """
                const el = document.querySelector('.jobs-search-results-list') || 
                          document.querySelector('[data-test-job-search-results-list]') ||
                          document.querySelector('ul');
                if (el) el.scrollTop += 600;
                """
            )
            await human_delay(0.5, 1.5)

            # Click "See more jobs" button if present (avoid strict mode violation)
            see_more = page.locator("button.infinite-scroller__show-more-button")
            if await see_more.count() > 0 and await see_more.first.is_visible():
                try:
                    await see_more.first.click()
                    await human_delay(0.5, 1.5)
                except Exception:
                    pass  # Button might have disappeared

        total = await page.locator(working_selector).count()
        logger.info("Finished scrolling — {} job cards loaded", total)

    # ──────────────────────────────────────────────────────────────
    #  Extract job cards from the page
    # ──────────────────────────────────────────────────────────────
    async def _extract_jobs(self, page: Page) -> list[dict[str, Any]]:
        """Parse visible job cards into a list of job dicts."""
        jobs: list[dict[str, Any]] = []
        
        # DEBUG: Log page state
        page_url = page.url
        page_title = await page.title()
        logger.info("📄 Extracting from: {} ({})", page_url[:80], page_title[:60])
        
        # Check if we're on the jobs search page
        if "linkedin.com" not in page_url:
            logger.error("❌ Not on LinkedIn! URL: {}", page_url)
            return []
        
        # Prefer logged-in selectors only (public .base-card causes bad UK URLs / unknown ids)
        card_selectors = [
            "[data-job-id]",
            "li[data-job-id]",
            ".job-card-container",
            ".jobs-search-results__list-item",
        ]
        
        cards = None
        for sel in card_selectors:
            count = await page.locator(sel).count()
            if count > 0:
                cards = page.locator(sel)
                logger.info("✓ Using selector '{}' (found {} cards)", sel, count)
                break
        
        if cards is None:
            logger.warning("❌ No job card selectors found any cards")
            return []
        
        count = await cards.count()
        max_per_page = 20
        for i in range(min(count, max_per_page)):
            try:
                card = cards.nth(i)

                # Title - try multiple selectors (logged-in + public)
                title_el = card.locator(
                    ".job-card-list__title--link span, .job-card-list__title, "
                    "[data-test-job-card-title], .base-search-card__title, "
                    ".base-card__full-link, h3.base-search-card__title, "
                    "a.base-card__full-link, h3, a span"
                )
                title = ""
                if await title_el.count() > 0:
                    title = (await title_el.first.inner_text()).strip()

                # Company - try multiple selectors (logged-in + public)
                company_el = card.locator(
                    ".artdeco-entity-lockup__subtitle span, "
                    ".job-card-container__primary-description, "
                    "[data-test-company-name], .base-search-card__subtitle, "
                    "h4.base-search-card__subtitle, h4 a, h4"
                )
                company = ""
                if await company_el.count() > 0:
                    company = (await company_el.first.inner_text()).strip()

                # Location - try multiple selectors (logged-in + public)
                loc_el = card.locator(
                    ".artdeco-entity-lockup__caption span, "
                    ".job-card-container__metadata-wrapper li, "
                    "[data-test-location], .job-search-card__location, "
                    "span.job-search-card__location"
                )
                location = ""
                if await loc_el.count() > 0:
                    location = (await loc_el.first.inner_text()).strip()

                # Job URL / ID
                job_id = None
                url = ""

                job_id_attr = await card.get_attribute("data-job-id")
                if job_id_attr and re.search(r"\d", job_id_attr):
                    # data-job-id can be "123" or "123,456"
                    job_id = re.sub(r"[^\d].*", "", job_id_attr.strip().split(",")[0])
                    if job_id:
                        url = f"https://www.linkedin.com/jobs/view/{job_id}/"

                if not job_id:
                    link_el = card.locator("a[href*='/jobs/view/'], a[href*='/jobs/']")
                    if await link_el.count() > 0:
                        href = await link_el.first.get_attribute("href") or ""
                        m = re.search(r"/jobs/view/(\d+)", href) or re.search(
                            r"-(\d{8,})(?:\?|$|/)", href
                        )
                        if m:
                            job_id = m.group(1)
                            url = f"https://www.linkedin.com/jobs/view/{job_id}/"

                if not job_id or not job_id.isdigit():
                    logger.debug("Skipping card {} — no numeric job id", i)
                    continue

                # Easy Apply badge (also treat f_AL search results as easy when badge missing)
                easy_badge = card.locator(
                    ".job-card-container__apply-method, span:has-text('Easy Apply'), "
                    "[data-test-easy-apply], li:has-text('Easy Apply')"
                )
                easy_apply = await easy_badge.count() > 0
                if "f_AL=true" in page.url:
                    easy_apply = True

                if not title or not company:
                    logger.debug("Skipping incomplete job card {}: title='{}', company='{}'", i, title, company)
                    continue

                # Skip clearly non-India locations for this profile
                loc_l = location.lower()
                if any(x in loc_l for x in ("united kingdom", "london", "uk ", " england")):
                    logger.debug("Skipping non-India location: {}", location)
                    continue

                jobs.append({
                    "source": self.SOURCE,
                    "job_id": job_id,
                    "title": title.split("\n")[0].strip(),
                    "company": company.split("\n")[0].strip(),
                    "location": location,
                    "url": url,
                    "easy_apply": easy_apply,
                    "description": None,
                })
                logger.info("Extracted job {}: {} at {}", job_id, title.split(chr(10))[0].strip(), company.split(chr(10))[0].strip())
            except Exception as exc:
                logger.warning("Failed to parse card {}: {}", i, exc)
                continue

        logger.info("Extracted {} jobs from page", len(jobs))
        return jobs

    # ──────────────────────────────────────────────────────────────
    #  Get job description from detail panel
    # ──────────────────────────────────────────────────────────────
    async def get_job_description(self, page: Page, job_url: str) -> str:
        """Navigate to a job detail page and extract the description text."""
        try:
            if page.url != job_url:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                await human_delay(2.0, 3.5)

            selectors = [
                "#job-details",
                ".jobs-box__html-content",
                ".jobs-description__content",
                ".jobs-description-content__text",
                "article.jobs-description__container",
                ".jobs-description",
                "[class*='jobs-description']",
            ]
            for sel in selectors:
                loc = page.locator(sel)
                try:
                    await loc.first.wait_for(state="visible", timeout=4_000)
                except PwTimeout:
                    continue
                if await loc.count() > 0:
                    # Expand "See more" if present
                    see_more = page.locator(
                        "button:has-text('See more'), "
                        "button.jobs-description__footer-button, "
                        "button[aria-label*='see more' i]"
                    )
                    if await see_more.count() > 0:
                        try:
                            await see_more.first.click(timeout=2000)
                            await human_delay(0.3, 0.6)
                        except Exception:
                            pass
                    desc = (await loc.first.inner_text()).strip()
                    if len(desc) > 40:
                        return desc
            logger.warning("No job description element found for {}", job_url)
            return ""
        except Exception as exc:
            logger.warning("Failed to extract job description for {}: {}", job_url, exc)
            return ""
