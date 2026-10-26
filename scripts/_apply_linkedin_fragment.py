    async def _find_easy_apply_button(self, page: Page, scope=None):
        """Return Easy Apply locator, 'js_clicked', 'applied', 'external', or None."""
        root = scope if scope is not None else page
        deadline = asyncio.get_event_loop().time() + 18
        while asyncio.get_event_loop().time() < deadline:
            await self._dismiss_overlays(page)

            strategies = [
                root.get_by_role("button", name=re.compile(r"easy\s*apply", re.I)),
                root.locator("button.jobs-apply-button").filter(
                    has_text=re.compile(r"easy\s*apply", re.I)
                ),
                root.locator("button[aria-label*='Easy Apply' i]"),
                root.locator(".jobs-s-apply button").filter(
                    has_text=re.compile(r"easy\s*apply", re.I)
                ),
                root.locator("button:has-text('Easy Apply')"),
            ]
            for loc in strategies:
                try:
                    if await loc.count() == 0:
                        continue
                    btn = loc.first
                    if await btn.is_visible():
                        text = ((await btn.inner_text()) or "").lower()
                        aria = ((await btn.get_attribute("aria-label")) or "").lower()
                        if "applied" in text or "applied" in aria:
                            return "applied"
                        if "easy" in text or "easy" in aria:
                            return btn
                except Exception:
                    continue

            found = await page.evaluate(
                """() => {
                    const roots = [
                      document.querySelector('.jobs-details'),
                      document.querySelector('.scaffold-layout__detail'),
                      document.querySelector('.jobs-search__job-details'),
                      document.body,
                    ].filter(Boolean);
                    for (const root of roots) {
                      const nodes = [...root.querySelectorAll('button, [role="button"]')];
                      for (const b of nodes) {
                        const t = ((b.innerText || '') + ' ' + (b.getAttribute('aria-label') || ''))
                          .replace(/\\s+/g, ' ').trim().toLowerCase();
                        if (t.includes('easy apply')) {
                          const r = b.getBoundingClientRect();
                          if (r.width > 0 && r.height > 0) return 'easy';
                        }
                      }
                    }
                    const detail = document.querySelector('.jobs-details, .scaffold-layout__detail, .jobs-search__job-details') || document.body;
                    const txt = (detail.innerText || '').toLowerCase();
                    if (txt.includes('responses managed off linkedin')) return 'external';
                    const nodes = [...detail.querySelectorAll('button, a')];
                    for (const b of nodes) {
                      const t = ((b.innerText || '') + ' ' + (b.getAttribute('aria-label') || ''))
                        .replace(/\\s+/g, ' ').trim().toLowerCase();
                      if ((t === 'apply' || t.startsWith('apply ')) && !t.includes('easy')) {
                        // external link icon often present
                        if (b.querySelector('li-icon[type=\"link-external\"], svg[data-test-icon=\"link-external-small\"]')
                            || t.includes('company')) return 'external';
                      }
                    }
                    return null;
                }"""
            )
            if found == "easy":
                loc = page.locator("button").filter(has_text=re.compile(r"easy\s*apply", re.I))
                if await loc.count() > 0:
                    return loc.first
                await page.evaluate(
                    """() => {
                        const nodes = [...document.querySelectorAll('button, [role="button"]')];
                        const b = nodes.find(x => {
                          const t = ((x.innerText || '') + ' ' + (x.getAttribute('aria-label') || ''))
                            .replace(/\\s+/g, ' ').trim().toLowerCase();
                          return t.includes('easy apply');
                        });
                        if (b) b.click();
                    }"""
                )
                return "js_clicked"
            if found == "external" and asyncio.get_event_loop().time() + 4 > deadline:
                return "external"

            await human_delay(0.7, 1.1)

        return None

    async def _apply_linkedin(self, page: Page, job: dict[str, Any]) -> ApplyResult:
        jid = normalize_linkedin_job_id(job)
        if not jid:
            return ApplyResult("failed", "missing numeric job id")

        search_url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?currentJobId={jid}&f_AL=true&geoId=102713980&sortBy=DD"
        )
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            logger.warning("Search nav failed: {}", exc)
            await page.goto(
                f"https://www.linkedin.com/jobs/view/{jid}/",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
        await human_delay(2.5, 4)
        await self._dismiss_overlays(page)

        card = page.locator(
            f'li[data-job-id="{jid}"], div[data-job-id="{jid}"], [data-job-id="{jid}"]'
        )
        if await card.count() > 0:
            try:
                await card.first.click(timeout=4000)
                await human_delay(1.8, 2.8)
            except Exception:
                pass

        await self._dismiss_overlays(page)
        detail = page.locator(
            ".jobs-details, .scaffold-layout__detail, .jobs-search__job-details, main"
        ).first

        found = await self._find_easy_apply_button(page, scope=detail)
        if found == "applied":
            return ApplyResult("skipped", "already applied on LinkedIn")
        if found == "external":
            return ApplyResult("external", "external Apply (company site) — not auto-applied")

        easy_btn = found
        if easy_btn is None:
            await page.goto(
                f"https://www.linkedin.com/jobs/view/{jid}/",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            await human_delay(3, 4)
            found = await self._find_easy_apply_button(page)
            if found == "applied":
                return ApplyResult("skipped", "already applied on LinkedIn")
            if found == "external":
                return ApplyResult("external", "external Apply (company site) — not auto-applied")
            easy_btn = found

        if easy_btn is None:
            await take_screenshot(page, f"linkedin_no_btn_{jid}")
            try:
                labels = await page.evaluate(
                    """() => [...document.querySelectorAll('button')]
                       .slice(0, 30)
                       .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim())
                       .filter(Boolean)"""
                )
                logger.info("Visible buttons on job {}: {}", jid, labels[:15])
            except Exception:
                pass
            return ApplyResult("failed", "Easy Apply button not found")

        if easy_btn != "js_clicked":
            try:
                await easy_btn.scroll_into_view_if_needed()
                await human_delay(0.3, 0.6)
                await easy_btn.click(timeout=5_000)
            except Exception:
                try:
                    await easy_btn.click(force=True, timeout=5_000)
                except Exception as exc:
                    await take_screenshot(page, f"linkedin_click_fail_{jid}")
                    return ApplyResult("failed", f"could not click Easy Apply: {exc}")

        await human_delay(1.5, 2.5)

        modal = page.locator(
            ".jobs-easy-apply-modal, .jobs-easy-apply-content, "
            "div[data-test-modal-id='easy-apply-modal']"
        )
        try:
            await modal.first.wait_for(state="visible", timeout=12_000)
        except PwTimeout:
            if await page.locator(
                "text=/application (was )?sent/i, text=/submitted/i"
            ).count() > 0:
                return ApplyResult("applied", "submitted immediately")
            await take_screenshot(page, f"linkedin_no_modal_{jid}")
            return ApplyResult("failed", "Easy Apply modal did not open")

        for step in range(15):
            await self._dismiss_overlays(page)
            await self._fill_linkedin_form(page)

            submit = page.locator(
                "button[aria-label*='Submit application' i], "
                "button:has-text('Submit application'), "
                "button:has-text('Submit')"
            )
            if await submit.count() > 0:
                cand = submit.first
                try:
                    if await cand.is_enabled() and await cand.is_visible():
                        try:
                            box = page.locator(
                                "input[id*='follow-company'], #follow-company-checkbox"
                            )
                            if await box.count() > 0 and await box.first.is_checked():
                                await box.first.uncheck()
                        except Exception:
                            pass
                        await cand.click()
                        await human_delay(2, 3.5)
                        if await page.locator(
                            "text=/application (was )?sent/i, "
                            "text=/submitted/i, "
                            ".artdeco-inline-feedback--success, "
                            "button:has-text('Done')"
                        ).count() > 0:
                            try:
                                done = page.locator(
                                    "button:has-text('Done'), button[aria-label='Dismiss'], "
                                    "button.artdeco-modal__dismiss"
                                )
                                if await done.count() > 0:
                                    await done.first.click()
                            except Exception:
                                pass
                            return ApplyResult("applied", "submitted via Easy Apply")
                        if await modal.count() == 0:
                            return ApplyResult("applied", "modal closed after submit")
                except Exception as exc:
                    logger.debug("Submit click issue: {}", exc)

            next_btn = page.locator(
                "button[aria-label*='Continue' i], "
                "button[aria-label*='Next' i], "
                "button[aria-label*='Review' i], "
                "button:has-text('Next'), "
                "button:has-text('Review'), "
                "button:has-text('Continue')"
            )
            clicked_next = False
            if await next_btn.count() > 0:
                try:
                    nb = next_btn.first
                    if await nb.is_enabled() and await nb.is_visible():
                        await nb.click()
                        await human_delay(1.2, 2.2)
                        clicked_next = True
                except Exception:
                    pass

            if not clicked_next:
                await take_screenshot(page, f"linkedin_stuck_{jid}_s{step}")
                try:
                    close = page.locator(
                        "button[aria-label='Dismiss'], button.artdeco-modal__dismiss"
                    )
                    if await close.count() > 0:
                        await close.first.click()
                        discard = page.locator("button:has-text('Discard')")
                        if await discard.count() > 0:
                            await discard.first.click()
                except Exception:
                    pass
                return ApplyResult("failed", f"stuck on Easy Apply step {step}")

        return ApplyResult("failed", "Easy Apply exceeded max steps")

