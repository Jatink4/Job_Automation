"""
core/applicant.py — Auto-apply to LinkedIn Easy Apply + Naukri jobs.

Only handles in-platform Easy Apply (not external ATS).
"""

from __future__ import annotations

import asyncio
import random
import re
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Page, TimeoutError as PwTimeout

import config
from core import ai_helper
from core.browser import (
    BrowserManager,
    human_delay,
    take_screenshot,
)
from core.db import already_applied, record_application


class ApplyResult:
    def __init__(self, status: str, message: str = "") -> None:
        self.status = status  # applied | skipped | failed | external
        self.message = message


def normalize_linkedin_job_id(job: dict[str, Any]) -> str | None:
    """Extract numeric LinkedIn job id from job dict / URL."""
    jid = str(job.get("job_id") or "")
    if jid.isdigit():
        return jid
    url = job.get("url") or ""
    m = re.search(r"/jobs/view/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"-(\d{8,})(?:\?|$|/)", url)
    if m:
        return m.group(1)
    if jid.isdigit():
        return jid
    return None


class JobApplicant:
    """Applies to scored jobs that support LinkedIn Easy Apply / Naukri apply."""

    def __init__(self, browser: BrowserManager, resume: dict[str, Any]) -> None:
        self.browser = browser
        self.resume = resume
        self.personal = resume.get("personal", {})
        self.answers = resume.get("screening_answers", {})
        self.pdf_path = self._resolve_resume_pdf()

    def _resolve_resume_pdf(self) -> Path | None:
        path = config.RESUME_PDF_PATH
        if path.exists():
            return path
        # Prefer Resume/ folder (user-provided PDF)
        resume_dir = config.BASE_DIR / "Resume"
        if resume_dir.exists():
            pdfs = sorted(resume_dir.glob("*.pdf"))
            if pdfs:
                return pdfs[0]
        public = config.BASE_DIR / "public"
        for name in ("resume.pdf",):
            alt = public / name
            if alt.exists():
                return alt
        if public.exists():
            pdfs = sorted(public.glob("*.pdf"))
            if pdfs:
                return pdfs[0]
        logger.warning("Resume PDF not found — applications may fail without upload")
        return None

    async def apply_to_jobs(self, jobs: list[dict[str, Any]], max_apps: int) -> list[dict[str, Any]]:
        applied: list[dict[str, Any]] = []
        page = await self.browser.get_page()

        # Normalize IDs / URLs; drop junk
        cleaned: list[dict[str, Any]] = []
        for j in jobs:
            jid = normalize_linkedin_job_id(j)
            if j.get("source") == "linkedin":
                if not jid:
                    logger.debug("Drop job without numeric id: {}", j.get("title"))
                    continue
                j = {
                    **j,
                    "job_id": jid,
                    "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                    "easy_apply": True if j.get("easy_apply", True) else False,
                }
            cleaned.append(j)

        candidates = [
            j
            for j in cleaned
            if j.get("easy_apply")
            and not already_applied(j.get("source", ""), str(j.get("job_id", "")))
        ]
        candidates.sort(key=lambda j: j.get("ai_score", 0), reverse=True)

        logger.info(
            "Apply queue: {} Easy Apply jobs (cap {}), {} skipped/invalid",
            len(candidates),
            max_apps,
            len(jobs) - len(candidates),
        )

        for job in candidates[:max_apps]:
            source = job.get("source", "")
            title = job.get("title", "?")
            company = job.get("company", "?")
            logger.info("→ Applying: {} at {} ({})", title, company, source)

            try:
                if source == "linkedin":
                    result = await self._apply_linkedin(page, job)
                elif source == "naukri":
                    result = await self._apply_naukri(page, job)
                else:
                    result = ApplyResult("skipped", f"unsupported source: {source}")
            except Exception as exc:
                logger.exception("Apply crashed for {}: {}", job.get("job_id"), exc)
                result = ApplyResult("failed", str(exc))
                try:
                    await take_screenshot(page, f"fail_{job.get('job_id')}")
                except Exception:
                    pass

            job["apply_status"] = result.status
            job["apply_message"] = result.message
            record_application(job, result.status, result.message)

            if result.status == "applied":
                applied.append(job)
                logger.info("✓ Applied to {} at {}", title, company)
            else:
                logger.warning("✗ {} — {}: {}", result.status, title, result.message)

            delay = random.uniform(
                config.DELAY_BETWEEN_APPS_MIN,
                config.DELAY_BETWEEN_APPS_MAX,
            )
            logger.info("Waiting {:.0f}s before next application…", delay)
            await asyncio.sleep(delay)

        return applied

    # ── LinkedIn Easy Apply ─────────────────────────────────────────

    async def _dismiss_overlays(self, page: Page) -> None:
        await self._discard_save_dialog(page)

        for sel in (
            "button:has-text('Not now')",
            "button:has-text('No thanks')",
            "button:has-text('Skip')",
        ):
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    parent_is_easy = await loc.first.evaluate(
                        """e => !!(e.closest('.jobs-easy-apply-modal') || e.closest('[data-test-modal-id=\"easy-apply-modal\"]'))"""
                    )
                    if parent_is_easy:
                        continue
                    await loc.first.click(timeout=1500)
                    await human_delay(0.3, 0.6)
            except Exception:
                pass

    async def _find_easy_apply_button(self, page: Page, scope=None, timeout_s: float = 18):
        """Return Easy Apply locator, 'js_clicked', 'applied', 'external', or None.

        When *scope* is set (detail pane), never fall back to the job list —
        list rows also contain the text 'Easy Apply' and would false-match.
        """
        root = scope if scope is not None else page
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            await self._dismiss_overlays(page)

            # Wait out skeleton loaders in the detail pane
            try:
                loader = page.locator(
                    ".jobs-details .jobs-loader, .scaffold-layout__detail .jobs-loader, "
                    ".jobs-search__job-details .jobs-loader"
                )
                if await loader.count() > 0 and await loader.first.is_visible():
                    await human_delay(0.5, 0.8)
                    continue
            except Exception:
                pass

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

            # JS scan — scoped to detail pane when provided (never list + body)
            found = await page.evaluate(
                """(scoped) => {
                    const pickRoots = () => {
                      if (scoped) {
                        const d = document.querySelector(
                          '.jobs-details, .scaffold-layout__detail, .jobs-search__job-details, ' +
                          '.job-view-layout, .jobs-details__main-content, ' +
                          '.jobs-unified-top-card, main'
                        );
                        return d ? [d] : [];
                      }
                      return [
                        document.querySelector('.jobs-details'),
                        document.querySelector('.scaffold-layout__detail'),
                        document.querySelector('.jobs-search__job-details'),
                        document.querySelector('.job-view-layout'),
                        document.querySelector('main'),
                        document.body,
                      ].filter(Boolean);
                    };
                    const roots = pickRoots();
                    for (const root of roots) {
                      const txt = (root.innerText || '').toLowerCase();
                      if (txt.includes('responses managed off linkedin')) return 'external';
                      const nodes = [...root.querySelectorAll('button, [role="button"]')];
                      for (const b of nodes) {
                        const t = ((b.innerText || '') + ' ' + (b.getAttribute('aria-label') || ''))
                          .replace(/\\s+/g, ' ').trim().toLowerCase();
                        if (t.includes('applied') && !t.includes('easy')) return 'applied';
                        if (t.includes('easy apply')) {
                          const r = b.getBoundingClientRect();
                          if (r.width > 0 && r.height > 0) return 'easy';
                        }
                      }
                    }
                    return null;
                }""",
                scope is not None,
            )
            if found == "applied":
                return "applied"
            if found == "easy":
                # Prefer button inside detail pane
                detail_btn = page.locator(
                    ".jobs-details button, .scaffold-layout__detail button, "
                    ".jobs-search__job-details button, .job-view-layout button, "
                    "main button, .jobs-apply-button"
                ).filter(has_text=re.compile(r"easy\s*apply", re.I))
                if await detail_btn.count() > 0:
                    return detail_btn.first
                if scope is None:
                    loc = page.locator("button").filter(
                        has_text=re.compile(r"easy\s*apply", re.I)
                    )
                    if await loc.count() > 0:
                        return loc.first
                await page.evaluate(
                    """() => {
                        const root = document.querySelector(
                          '.jobs-details, .scaffold-layout__detail, .jobs-search__job-details, ' +
                          '.job-view-layout, main'
                        ) || document.body;
                        const nodes = [...root.querySelectorAll('button, [role="button"]')];
                        const b = nodes.find(x => {
                          const t = ((x.innerText || '') + ' ' + (x.getAttribute('aria-label') || ''))
                            .replace(/\\s+/g, ' ').trim().toLowerCase();
                          return t.includes('easy apply');
                        });
                        if (b) b.click();
                    }"""
                )
                return "js_clicked"
            if found == "external":
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
        return await self._complete_easy_apply_modal(page, jid)

    async def _force_click(self, locator) -> bool:
        """Click a button even if overlays intercept pointer events."""
        try:
            if await locator.count() == 0:
                return False
            el = locator.first
            if not await el.is_visible():
                return False
            try:
                disabled = await el.is_disabled()
                aria_dis = (await el.get_attribute("aria-disabled") or "").lower()
                if disabled or aria_dis == "true":
                    logger.debug("Primary button disabled — need more form fill")
                    return False
            except Exception:
                pass
            try:
                await el.scroll_into_view_if_needed(timeout=2_000)
            except Exception:
                pass
            try:
                await el.click(force=True, timeout=4_000)
                return True
            except Exception:
                pass
            try:
                await el.evaluate("e => e.click()")
                return True
            except Exception:
                return False
        except Exception:
            return False

    async def _discard_save_dialog(self, page: Page) -> None:
        try:
            discard = page.locator(
                "[data-test-modal-id='data-test-easy-apply-discard-confirmation'] "
                "button:has-text('Discard'), "
                "[role='dialog']:has-text('Save this application') button:has-text('Discard')"
            )
            if await discard.count() > 0 and await discard.first.is_visible():
                await self._force_click(discard)
                await human_delay(0.4, 0.8)
                return
            # Fallback text match
            if await page.get_by_text("Save this application", exact=False).count() > 0:
                d2 = page.get_by_role("button", name=re.compile(r"^discard$", re.I))
                if await d2.count() > 0:
                    await self._force_click(d2)
                    await human_delay(0.4, 0.8)
        except Exception:
            pass

    async def _modal_fingerprint(self, page: Page) -> str:
        try:
            return await page.evaluate(
                """() => {
                    const m = document.querySelector(
                      '.jobs-easy-apply-modal, [data-test-modal-id=\"easy-apply-modal\"]'
                    );
                    if (!m) return '';
                    const body = m.querySelector('.jobs-easy-apply-content, .artdeco-modal__content') || m;
                    const progress = m.querySelector('progress, [role=\"progressbar\"]');
                    const p = progress ? (progress.getAttribute('aria-valuenow') || progress.value || '') : '';
                    const btn = m.querySelector('footer button.artdeco-button--primary, .artdeco-modal__actionbar button.artdeco-button--primary');
                    const bt = btn ? (btn.innerText || '') : '';
                    return (p + '|' + bt + '|' + (body.innerText || '').slice(0, 600)).replace(/\\s+/g, ' ');
                }"""
            )
        except Exception:
            return ""

    async def _close_easy_apply_modal(self, page: Page) -> None:
        """Dismiss Easy Apply modal + discard confirmation so search stays usable."""
        try:
            close = page.locator(
                ".jobs-easy-apply-modal button[aria-label='Dismiss'], "
                "[data-test-modal-id='easy-apply-modal'] button[aria-label='Dismiss'], "
                ".jobs-easy-apply-modal button.artdeco-modal__dismiss"
            )
            if await close.count() > 0 and await close.first.is_visible():
                await self._force_click(close)
                await human_delay(0.5, 1.0)
            await self._discard_save_dialog(page)
            # Escape as last resort
            modal = page.locator(
                ".jobs-easy-apply-modal, [data-test-modal-id='easy-apply-modal']"
            )
            if await modal.count() > 0 and await modal.first.is_visible():
                await page.keyboard.press("Escape")
                await human_delay(0.4, 0.8)
                await self._discard_save_dialog(page)
        except Exception:
            pass

    async def _modal_primary(self, page: Page):
        return page.locator(
            ".jobs-easy-apply-modal footer button.artdeco-button--primary, "
            "[data-test-modal-id='easy-apply-modal'] footer button.artdeco-button--primary, "
            ".jobs-easy-apply-modal .artdeco-modal__actionbar button.artdeco-button--primary, "
            "[data-test-modal-id='easy-apply-modal'] .artdeco-modal__actionbar button.artdeco-button--primary"
        )

    async def _application_sent(self, page: Page) -> bool:
        """True if LinkedIn shows application submitted / Done confirmation."""
        checks = [
            page.get_by_text(re.compile(r"application (was )?sent", re.I)),
            page.get_by_text(re.compile(r"submitted your application", re.I)),
            page.locator(".artdeco-inline-feedback--success"),
            page.get_by_role("button", name=re.compile(r"^done$", re.I)),
        ]
        for loc in checks:
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _complete_easy_apply_modal(self, page: Page, jid: str) -> ApplyResult:
        modal = page.locator(
            ".jobs-easy-apply-modal, [data-test-modal-id='easy-apply-modal']"
        )
        try:
            await modal.first.wait_for(state="visible", timeout=12_000)
        except PwTimeout:
            if await self._application_sent(page):
                return ApplyResult("applied", "submitted immediately")
            await take_screenshot(page, f"linkedin_no_modal_{jid}")
            return ApplyResult("failed", "Easy Apply modal did not open")

        stagnant = 0
        last_fp = ""

        for step in range(12):
            await self._discard_save_dialog(page)
            await self._fill_linkedin_form(page)
            await human_delay(0.8, 1.2)

            fp_before = await self._modal_fingerprint(page)
            primary = await self._modal_primary(page)

            # Submit?
            submit = page.locator(
                ".jobs-easy-apply-modal button[aria-label*='Submit application' i], "
                "[data-test-modal-id='easy-apply-modal'] button[aria-label*='Submit application' i], "
                ".jobs-easy-apply-modal button:has-text('Submit application'), "
                "[data-test-modal-id='easy-apply-modal'] button:has-text('Submit application')"
            )
            if await submit.count() == 0:
                submit = primary.filter(has_text=re.compile(r"submit", re.I))

            if await submit.count() > 0 and await submit.first.is_visible():
                try:
                    box = page.locator(
                        "input[id*='follow-company'], #follow-company-checkbox"
                    )
                    if await box.count() > 0 and await box.first.is_checked():
                        await box.first.uncheck()
                except Exception:
                    pass
                if await self._force_click(submit):
                    await human_delay(2.5, 4)
                    if await self._application_sent(page):
                        try:
                            done = page.get_by_role(
                                "button", name=re.compile(r"^done$", re.I)
                            )
                            if await done.count() > 0:
                                await self._force_click(done)
                        except Exception:
                            pass
                        return ApplyResult("applied", "submitted via Easy Apply")
                    if await modal.count() == 0 or not await modal.first.is_visible():
                        return ApplyResult("applied", "modal closed after submit")
                    # Validation on review — refill and retry
                    stagnant += 1
                    if stagnant >= 3:
                        await take_screenshot(page, f"linkedin_submit_stuck_{jid}")
                        await self._close_easy_apply_modal(page)
                        return ApplyResult("failed", "submit blocked by validation")
                    continue

            # Next / Review / Continue — scoped to modal footer only
            next_btn = primary.filter(
                has_text=re.compile(r"next|review|continue", re.I)
            )
            if await next_btn.count() == 0:
                next_btn = page.locator(
                    ".jobs-easy-apply-modal footer button:has-text('Next'), "
                    ".jobs-easy-apply-modal footer button:has-text('Review'), "
                    ".jobs-easy-apply-modal footer button:has-text('Continue'), "
                    "[data-test-modal-id='easy-apply-modal'] footer button:has-text('Next'), "
                    "[data-test-modal-id='easy-apply-modal'] footer button:has-text('Review'), "
                    "button[aria-label*='Continue to next step' i], "
                    "button[aria-label*='Review your application' i]"
                )

            if await next_btn.count() == 0 or not await next_btn.first.is_visible():
                # Try any footer primary
                if await primary.count() == 0 or not await primary.first.is_visible():
                    await take_screenshot(page, f"linkedin_stuck_{jid}_s{step}")
                    await self._close_easy_apply_modal(page)
                    return ApplyResult("failed", f"no Next/Submit on step {step}")
                next_btn = primary

            clicked = await self._force_click(next_btn)
            if not clicked:
                await take_screenshot(page, f"linkedin_stuck_{jid}_s{step}")
                await self._close_easy_apply_modal(page)
                return ApplyResult("failed", f"could not click Next on step {step}")

            await human_delay(1.8, 2.8)
            fp_after = await self._modal_fingerprint(page)

            # Success after next (sometimes submit lands on thank-you without Submit btn)
            if await self._application_sent(page):
                try:
                    done = page.get_by_role(
                        "button", name=re.compile(r"^done$", re.I)
                    )
                    if await done.count() > 0:
                        await self._force_click(done)
                except Exception:
                    pass
                return ApplyResult("applied", "submitted via Easy Apply")

            if fp_after and fp_after == fp_before:
                stagnant += 1
                logger.warning(
                    "Easy Apply step {} did not advance (stagnant={})", step, stagnant
                )
                # Log validation errors
                try:
                    errs = page.locator(
                        ".jobs-easy-apply-modal .artdeco-inline-feedback--error, "
                        ".jobs-easy-apply-modal [data-test-form-element-error-messages], "
                        ".fb-dash-form-element__error-field"
                    )
                    if await errs.count() > 0:
                        msg = (await errs.first.inner_text()).strip()[:200]
                        logger.warning("Validation: {}", msg)
                except Exception:
                    pass
                # Force-overwrite contact fields and retry fill
                await self._fill_linkedin_form(page, force=True)
                if stagnant >= 3:
                    await take_screenshot(page, f"linkedin_stuck_{jid}_s{step}")
                    await self._close_easy_apply_modal(page)
                    return ApplyResult(
                        "failed", f"stuck on Easy Apply step {step} (validation)"
                    )
            else:
                stagnant = 0
                last_fp = fp_after
                logger.info("Easy Apply step {} → advanced", step)

        await take_screenshot(page, f"linkedin_maxsteps_{jid}")
        await self._close_easy_apply_modal(page)
        return ApplyResult("failed", "Easy Apply exceeded max steps")


    async def _ensure_india_phone_country(self, page: Page) -> None:
        """Select India (+91) in LinkedIn phone country dropdown if unset."""
        try:
            # Common LinkedIn pattern: button/select labeled Phone country code
            triggers = page.locator(
                ".jobs-easy-apply-modal label:has-text('Phone country code') "
                "~ div button, "
                ".jobs-easy-apply-modal label:has-text('Phone country code') "
                "+ div button, "
                ".jobs-easy-apply-modal div.fb-dash-form-element:has-text('Phone country code') button, "
                ".jobs-easy-apply-modal button[aria-label*='Phone country' i], "
                ".jobs-easy-apply-modal select[id*='phoneNumber-country'], "
                ".jobs-easy-apply-modal select[aria-label*='country' i]"
            )
            # Native <select>
            native = page.locator(
                ".jobs-easy-apply-modal select[id*='phoneNumber'], "
                ".jobs-easy-apply-modal select[aria-label*='country' i]"
            )
            for i in range(await native.count()):
                sel = native.nth(i)
                if not await sel.is_visible():
                    continue
                opts = await sel.locator("option").all_inner_texts()
                for o in opts:
                    if "india" in o.lower() or "+91" in o:
                        await sel.select_option(label=o)
                        logger.info("Selected phone country: {}", o.strip()[:40])
                        return

            n = await triggers.count()
            for i in range(min(n, 6)):
                btn = triggers.nth(i)
                if not await btn.is_visible():
                    continue
                text = ((await btn.inner_text()) or "").strip()
                if "+91" in text or "india" in text.lower():
                    return
                # Open dropdown
                await btn.click(force=True, timeout=3_000)
                await human_delay(0.5, 0.9)
                # Typeahead search if present
                search = page.locator(
                    ".artdeco-typeahead__input, "
                    "input[role='combobox']:visible, "
                    "[data-test-single-typeahead-entity-form-component] input"
                )
                if await search.count() > 0 and await search.first.is_visible():
                    await search.first.fill("")
                    await search.first.type("India", delay=40)
                    await human_delay(0.7, 1.1)
                # Pick India (+91)
                opt = page.locator(
                    "[role='option']:has-text('India (+91)'), "
                    "[role='option']:has-text('India'), "
                    ".artdeco-dropdown__item:has-text('India'), "
                    "div[role='listbox'] div:has-text('+91')"
                )
                if await opt.count() > 0:
                    await opt.first.click(force=True)
                    await human_delay(0.4, 0.7)
                    logger.info("Selected India (+91) phone country")
                    return
                # Keyboard select first match
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
                await human_delay(0.3, 0.5)
                text2 = ((await btn.inner_text()) or "").strip()
                if "+91" in text2 or "india" in text2.lower():
                    return
                await page.keyboard.press("Escape")
        except Exception as exc:
            logger.debug("Country select skipped: {}", exc)

    async def _pick_city_suggestion(self, page: Page) -> None:
        """If location typeahead suggestions are open, pick the first match."""
        try:
            opts = page.locator(
                ".jobs-easy-apply-modal [role='option'], "
                ".jobs-easy-apply-modal .basic-typeahead__triggered-content [role='option'], "
                ".search-typeahead-v2__hit"
            )
            if await opts.count() == 0:
                return
            first = opts.first
            if await first.is_visible():
                await first.click(force=True)
                await human_delay(0.3, 0.5)
        except Exception:
            pass

    async def _fill_linkedin_form(self, page: Page, force: bool = False) -> None:
        """Fill text inputs, textareas, selects, radios in the Easy Apply modal."""
        if self.pdf_path:
            file_inputs = page.locator(
                ".jobs-easy-apply-modal input[type='file'], "
                ".jobs-document-upload input[type='file'], "
                "[data-test-modal-id='easy-apply-modal'] input[type='file']"
            )
            if await file_inputs.count() > 0:
                try:
                    await file_inputs.first.set_input_files(str(self.pdf_path))
                    await human_delay(1, 2)
                    logger.debug("Uploaded resume PDF")
                except Exception as exc:
                    logger.debug("Resume upload skipped: {}", exc)

        await self._ensure_india_phone_country(page)

        inputs = page.locator(
            ".jobs-easy-apply-modal input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio']), "
            "[data-test-modal-id='easy-apply-modal'] input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio'])"
        )
        count = await inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            try:
                if not await el.is_visible():
                    continue
                current = (await el.input_value() or "").strip()
                label = await self._field_label(page, el)
                label_l = label.lower()
                value = await self._answer_for_label(label)
                if not value:
                    continue
                is_contact = any(
                    k in label_l
                    for k in ("phone", "mobile", "email", "city", "first name", "last name")
                )
                invalid = False
                try:
                    invalid = await el.evaluate(
                        "e => e.getAttribute('aria-invalid') === 'true' || e.classList.contains('error')"
                    )
                except Exception:
                    pass
                if current and not force and not invalid and not (
                    is_contact and force
                ):
                    # Overwrite wrong phone even when not forced
                    if "phone" in label_l or "mobile" in label_l:
                        digits = re.sub(r"\D", "", current)
                        want = re.sub(r"\D", "", value)
                        if want and digits.endswith(want[-10:]):
                            continue
                        # different number — rewrite
                    else:
                        continue
                await el.click()
                await el.fill("")
                await el.type(value, delay=random.randint(25, 60))
                await human_delay(0.15, 0.35)
                if any(k in label_l for k in ("city", "location")):
                    await self._pick_city_suggestion(page)
            except Exception as exc:
                logger.debug("Skip input {}: {}", i, exc)

        # Re-try country after phone field is filled (LinkedIn sometimes needs both)
        await self._ensure_india_phone_country(page)

        areas = page.locator(
            ".jobs-easy-apply-modal textarea, "
            "[data-test-modal-id='easy-apply-modal'] textarea"
        )
        for i in range(await areas.count()):
            el = areas.nth(i)
            try:
                if not await el.is_visible():
                    continue
                current = (await el.input_value() or "").strip()
                if current and not force:
                    continue
                label = await self._field_label(page, el)
                value = await self._answer_for_label(label, long_form=True)
                if value:
                    await el.fill(value)
                    await human_delay(0.2, 0.5)
            except Exception as exc:
                logger.debug("Skip textarea {}: {}", i, exc)

        selects = page.locator(
            ".jobs-easy-apply-modal select, "
            "[data-test-modal-id='easy-apply-modal'] select"
        )
        for i in range(await selects.count()):
            el = selects.nth(i)
            try:
                if not await el.is_visible():
                    continue
                selected = await el.evaluate("e => e.selectedIndex")
                if selected > 0 and not force:
                    continue
                label = await self._field_label(page, el)
                value = await self._answer_for_label(label)
                options = await el.locator("option").all_inner_texts()
                choice = self._best_option(options, value or label)
                if choice:
                    await el.select_option(label=choice)
            except Exception as exc:
                logger.debug("Skip select {}: {}", i, exc)

        # Typeahead / select-like dropdowns that still show Select…
        years_num = re.sub(r"[^\d].*", "", str(self.answers.get("years_of_experience", "0"))) or "0"
        try:
            unfilled = page.locator(
                ".jobs-easy-apply-modal button:has-text('Select'), "
                ".jobs-easy-apply-modal button:has-text('Select an option'), "
                ".jobs-easy-apply-modal button:has-text('Choose'), "
                ".jobs-easy-apply-modal button[aria-label*='Select' i], "
                ".jobs-easy-apply-modal div[role='combobox'], "
                ".jobs-easy-apply-modal button[aria-expanded='false'][aria-required='true']"
            )
            for i in range(min(await unfilled.count(), 8)):
                btn = unfilled.nth(i)
                if not await btn.is_visible():
                    continue
                btn_txt = ((await btn.inner_text()) or "").strip().lower()
                # Already chosen a real value
                if btn_txt and not any(
                    x in btn_txt for x in ("select", "choose", "please", "option")
                ):
                    # Keep year-like empty? if it already has a year selected, skip
                    if re.search(r"\d", btn_txt) or btn_txt in ("yes", "no", "immediate"):
                        continue
                # Prefer label context near the button (years vs yes/no)
                near = ""
                try:
                    near = ((await btn.evaluate(
                        "e => (e.closest('fieldset, .fb-dash-form-element, div')?.innerText || e.parentElement?.innerText || '')"
                    )) or "").lower()
                except Exception:
                    pass
                await btn.click(force=True)
                await human_delay(0.35, 0.7)
                opt = page.locator(
                    "[role='listbox'] [role='option'], "
                    "[role='option'], "
                    ".artdeco-dropdown__item, "
                    ".artdeco-typeahead__result"
                )
                if await opt.count() > 0:
                    texts = []
                    for j in range(min(await opt.count(), 30)):
                        texts.append(((await opt.nth(j).inner_text()) or "").strip())
                    picked_idx = None
                    # Years-of-experience style lists: "0 year", "1 year", …
                    yearish = any(re.search(r"^\d+\s*years?$", t.lower()) for t in texts if t)
                    if yearish or "year" in near or "experience" in near:
                        prefer = [
                            f"{years_num} year",
                            f"{years_num} years",
                            years_num,
                            "0 year",
                            "0 years",
                            "less than 1 year",
                            "1 year",
                            "1 years",
                        ]
                        for want in prefer:
                            for j, t in enumerate(texts):
                                tl = t.lower()
                                if tl == want or tl.startswith(want + " ") or tl == f"{want}s":
                                    picked_idx = j
                                    break
                            if picked_idx is not None:
                                break
                    if picked_idx is None and any(k in near for k in ("authoriz", "eligib", "relocat", "sponsor", "remote", "hybrid", "willing")):
                        for j, t in enumerate(texts):
                            if t.lower() in ("yes", "true", "immediate"):
                                picked_idx = j
                                break
                    if picked_idx is None:
                        for j, t in enumerate(texts):
                            if t.lower() in ("yes", "immediate", "fresher", "1", "1 year", "1 years"):
                                picked_idx = j
                                break
                    if picked_idx is None:
                        # Skip placeholder "Select…"
                        for j, t in enumerate(texts):
                            if t and "select" not in t.lower() and "choose" not in t.lower():
                                picked_idx = j
                                break
                    if picked_idx is not None:
                        await opt.nth(picked_idx).click(force=True)
                await human_delay(0.2, 0.4)
        except Exception as exc:
            logger.debug("Dropdown fill skipped: {}", exc)

        await self._fill_radio_groups(page)

        # Required consent / acknowledgment checkboxes (not follow-company)
        checks = page.locator(
            ".jobs-easy-apply-modal input[type='checkbox'], "
            ".jobs-easy-apply-content input[type='checkbox']"
        )
        for i in range(await checks.count()):
            el = checks.nth(i)
            try:
                if not await el.is_visible():
                    continue
                eid = (await el.get_attribute("id") or "").lower()
                if "follow" in eid:
                    continue
                if await el.is_checked():
                    continue
                # Check required-looking boxes
                required = await el.evaluate(
                    "e => e.required || e.getAttribute('aria-required') === 'true'"
                )
                label = (await self._field_label(page, el)).lower()
                if required or any(
                    k in label
                    for k in ("agree", "confirm", "acknowledge", "certify", "consent", "true")
                ):
                    await el.check()
            except Exception as exc:
                logger.debug("Skip checkbox {}: {}", i, exc)

    async def _fill_radio_groups(self, page: Page) -> None:
        """Fill native and ARIA radio groups in the Easy Apply modal."""
        modal = page.locator(
            ".jobs-easy-apply-modal, [data-test-modal-id='easy-apply-modal']"
        ).first

        async def _group_question(container) -> str:
            try:
                return ((await container.evaluate(
                    """(el) => {
                        const fs = el.closest('fieldset');
                        if (fs) {
                            const leg = fs.querySelector('legend');
                            if (leg) return leg.innerText;
                        }
                        const wrap = el.closest(
                          '.fb-dash-form-element, .jobs-easy-apply-form-element, [data-test-form-element]'
                        );
                        if (wrap) {
                            const q = wrap.querySelector(
                              'legend, label:not([for]), span[data-test-form-element-label], .fb-dash-form-element__label'
                            );
                            if (q) return q.innerText;
                            return wrap.innerText.split('\\n')[0] || '';
                        }
                        return '';
                    }"""
                )) or "").strip()[:200]
            except Exception:
                return ""

        async def _pick_option(question: str, options: list[tuple[Any, str]]) -> Any | None:
            if not options:
                return None
            texts = [t for _, t in options if t]
            hint = await self._answer_for_label(question)
            choice = self._best_option(texts, hint) or self._best_option(texts, question)
            if choice:
                for el, txt in options:
                    if txt.strip().lower() == choice.strip().lower():
                        return el
                    if choice.lower() in txt.lower():
                        return el
            q = question.lower()
            prefer: list[str] = []
            if any(k in q for k in ("sponsor", "visa")):
                prefer = ["no", "false"]
            elif any(k in q for k in ("authoriz", "eligible", "relocat", "remote", "willing", "citizen")):
                prefer = ["yes", "true"]
            elif any(k in q for k in ("year", "experience", "exp")):
                prefer = ["0", "0 year", "0 years", "less than 1", "1 year", "1", "fresher"]
            elif any(k in q for k in ("intern", "internship")):
                prefer = ["yes", "true"]
            for want in prefer:
                for el, txt in options:
                    if txt.lower() == want or txt.lower().startswith(want):
                        return el
            for el, txt in options:
                if txt.lower() in ("yes", "true", "0", "0 years", "fresher", "immediate"):
                    return el
            return options[0][0]

        async def _click_radio(el) -> None:
            try:
                if await el.is_checked():
                    return
            except Exception:
                pass
            try:
                await el.check(force=True)
                return
            except Exception:
                pass
            try:
                await el.click(force=True)
            except Exception:
                pass

        # Native <input type="radio">
        seen_names: set[str] = set()
        native = modal.locator("input[type='radio']")
        for i in range(await native.count()):
            el = native.nth(i)
            try:
                if not await el.is_visible():
                    continue
                name = await el.get_attribute("name") or f"native-{i}"
                if name in seen_names:
                    continue
                seen_names.add(name)
                group = modal.locator(f"input[type='radio'][name='{name}']")
                options: list[tuple[Any, str]] = []
                for j in range(await group.count()):
                    r = group.nth(j)
                    txt = ""
                    lid = await r.get_attribute("id")
                    if lid:
                        lab = modal.locator(f"label[for='{lid}']")
                        if await lab.count():
                            txt = (await lab.first.inner_text()).strip()
                    if not txt:
                        try:
                            txt = ((await r.evaluate(
                                "e => (e.closest('label')?.innerText || e.parentElement?.innerText || '').trim()"
                            )) or "").split("\n")[0].strip()
                        except Exception:
                            pass
                    options.append((r, txt))
                question = await _group_question(group.first)
                pick = await _pick_option(question, options)
                if pick:
                    await _click_radio(pick)
            except Exception as exc:
                logger.debug("Skip native radio {}: {}", i, exc)

        # LinkedIn ARIA role="radio" (custom UI)
        seen_aria: set[str] = set()
        aria_groups = modal.locator("[role='radiogroup']")
        for i in range(await aria_groups.count()):
            grp = aria_groups.nth(i)
            try:
                if not await grp.is_visible():
                    continue
                key = ((await grp.get_attribute("aria-label")) or "") + str(i)
                if key in seen_aria:
                    continue
                seen_aria.add(key)
                question = (
                    (await grp.get_attribute("aria-label"))
                    or await _group_question(grp)
                )
                opts = grp.locator("[role='radio']")
                options = []
                for j in range(await opts.count()):
                    o = opts.nth(j)
                    txt = (
                        (await o.get_attribute("aria-label"))
                        or (await o.inner_text())
                        or ""
                    ).strip()
                    options.append((o, txt))
                pick = await _pick_option(question, options)
                if pick:
                    await pick.click(force=True)
                    await human_delay(0.15, 0.3)
            except Exception as exc:
                logger.debug("Skip aria radio group {}: {}", i, exc)

    async def _field_label(self, page: Page, el) -> str:
        try:
            labeled = await el.evaluate(
                """(e) => {
                    const id = e.id;
                    if (id) {
                        const lab = document.querySelector(`label[for="${id}"]`);
                        if (lab) return lab.innerText;
                    }
                    const parentLab = e.closest('label');
                    if (parentLab) return parentLab.innerText;
                    const formGroup = e.closest('.fb-dash-form-element, .jobs-easy-apply-form-element, div');
                    if (formGroup) {
                        const lab = formGroup.querySelector('label, legend, span, p');
                        if (lab) return lab.innerText;
                    }
                    return e.getAttribute('aria-label') || e.placeholder || '';
                }"""
            )
            return (labeled or "").strip()[:200]
        except Exception:
            return ""

    async def _apply_naukri(self, page: Page, job: dict[str, Any]) -> ApplyResult:
        url = job.get("url") or ""
        if not url:
            return ApplyResult("failed", "missing job URL")

        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await human_delay(2, 4)

        if await page.locator(
            "button:has-text('Applied'), span:has-text('Applied')"
        ).count() > 0:
            return ApplyResult("skipped", "already applied on Naukri")

        apply_btn = page.locator(
            "#apply-button, button:has-text('Apply'), .apply-button"
        ).first
        try:
            await apply_btn.wait_for(state="visible", timeout=8_000)
        except PwTimeout:
            return ApplyResult("failed", "Apply button not found")

        btn_text = (await apply_btn.inner_text()).strip().lower()
        if "applied" in btn_text:
            return ApplyResult("skipped", "already applied")

        await apply_btn.click()
        await human_delay(2, 4)

        if await page.locator("button:has-text('Applied'), span:has-text('Applied')").count() > 0:
            return ApplyResult("applied", "Naukri apply succeeded")

        return ApplyResult("applied", "Naukri apply clicked (assumed success)")

    async def _answer_for_label(self, label: str, long_form: bool = False) -> str:
        text = (label or "").lower()
        personal = self.personal
        ans = self.answers
        phone = personal.get("phone", "") or ""
        phone_digits = re.sub(r"\D", "", phone)
        local_phone = phone_digits
        if local_phone.startswith("91") and len(local_phone) >= 12:
            local_phone = local_phone[2:]

        # LinkedIn numeric year fields reject "0-1" — always use a whole number
        years_num = re.sub(r"[^\d].*", "", str(ans.get("years_of_experience", "0"))) or "0"
        prof_years = re.sub(
            r"[^\d].*", "", str(ans.get("professional_experience_years", years_num))
        ) or "0"
        intern_months = re.sub(r"[^\d].*", "", str(ans.get("internship_months", "3"))) or "3"
        ctc_current = re.sub(r"[^\d.]", "", str(ans.get("current_ctc", "0"))) or "0"
        ctc_expected = re.sub(r"[^\d.]", "", str(ans.get("expected_ctc", "4"))) or "4"

        rules: list[tuple[list[str], str]] = [
            (["phone", "mobile", "contact number", "mobile phone"], local_phone or phone),
            (["email", "e-mail"], personal.get("email", "")),
            (["city", "location", "current location"], personal.get("location", "")),
            (["first name", "fname"], (personal.get("name") or "").split(" ")[0]),
            (["last name", "lname", "surname"], (personal.get("name") or "").split(" ")[-1]),
            (["full name", "your name", "candidate name"], personal.get("name", "")),
            (["linkedin"], personal.get("linkedin_url", "")),
            (["portfolio", "website", "github"], personal.get("portfolio_url", "") or personal.get("github_url", "")),
            (["full-time", "full time", "professional experience", "paid experience", "relevant experience", "total experience"], prof_years),
            (["internship", "intern experience", "intern months"], intern_months if "month" in text else str(ans.get("internship_experience", "Yes"))),
            (["how many years", "years of experience", "year of experience", "years experience"], years_num),
            (["notice", "joining"], str(ans.get("notice_period", "Immediate"))),
            (["current ctc", "current salary", "present ctc", "current remuneration"], ctc_current),
            (["expected ctc", "expected salary", "desired ctc", "expected remuneration", "salary expectation"], ctc_expected),
            (["lpa", "lakhs", "salary in"], ctc_expected),
            (["relocat"], "Yes" if ans.get("willing_to_relocate") else "No"),
            (["authoriz", "eligible to work", "work permit"], str(ans.get("work_authorization", "Yes"))),
            (["sponsor"], "No" if not ans.get("sponsorship_required") else "Yes"),
            (["remote"], "Yes"),
            (["hybrid"], "Yes"),
            (["cgpa", "gpa", "grade"], str(ans.get("cgpa", "8.5"))),
            (["graduat"], str(ans.get("graduation_year", "2026"))),
        ]
        # Generic year/experience only when label looks numeric (avoid free-text fields)
        if re.search(r"\b(year|years|experience|exp)\b", text) and not long_form:
            rules.append((["year", "experience", "exp "], years_num))

        for keys, value in rules:
            if any(k in text for k in keys) and value:
                return str(value)

        if text.strip():
            try:
                return await ai_helper.answer_question(label, self.resume)
            except Exception:
                pass

        if long_form:
            return self.resume.get("summary", "")[:500]
        if re.search(r"\b(ctc|salary|lpa|year|years|experience|gpa|cgpa|month)\b", text):
            return prof_years if "professional" in text or "full-time" in text else years_num
        return "0"

    @staticmethod
    def _best_option(options: list[str], hint: str) -> str | None:
        cleaned = [o.strip() for o in options if o.strip() and o.strip().lower() not in ("select", "choose")]
        if not cleaned:
            return None
        hint_l = (hint or "").lower()
        for o in cleaned:
            if hint_l and hint_l in o.lower():
                return o
        for o in cleaned:
            if o.lower() in ("yes", "true", "0", "0 years", "fresher", "immediate"):
                return o
        return cleaned[0]
