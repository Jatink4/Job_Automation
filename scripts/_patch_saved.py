from pathlib import Path

p = Path(r"d:\Job bot\scrapers\linkedin.py")
text = p.read_text(encoding="utf-8")
start = text.index("    async def scrape_saved")
end = text.index("    async def scrape(self)")

new = '''    async def scrape_saved(self) -> list[dict[str, Any]]:
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
            """() => {
                const out = [];
                const seen = new Set();
                const add = (jobId, title, company) => {
                    if (!jobId || seen.has(jobId)) return;
                    seen.add(jobId);
                    out.push({
                        job_id: jobId,
                        title: (title || 'Saved job').trim().split('\\\\n')[0],
                        company: (company || 'Unknown').trim().split('\\\\n')[0],
                        url: 'https://www.linkedin.com/jobs/view/' + jobId + '/',
                    });
                };
                for (const a of document.querySelectorAll('a[href*=\"/jobs/view/\"]')) {
                    const m = a.href.match(/\\\\/jobs\\\\/view\\\\/(\\\\d+)/);
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
                    const m = String(urn).match(/(\\\\d{8,})/);
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
                snippet = (await page.inner_text("body"))[:500].replace("\\n", " ")
                logger.info("Saved page text sample: {}", snippet)
            except Exception:
                pass

        logger.info("Collected {} saved LinkedIn jobs", len(jobs))
        return jobs

'''

# Fix over-escaped JS in the evaluate string - write cleaner version
new = new.replace("split('\\\\n')", "split('\\\\n')")  # placeholder no-op

p.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("OK patched scrape_saved")
