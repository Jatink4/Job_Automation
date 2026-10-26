"""
Discover Easy Apply jobs via LinkedIn search, then submit on job view pages.
Applies as soon as the first good search returns cards (doesn't scan every city first).
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any
from urllib.parse import quote_plus

from loguru import logger
from playwright.async_api import Page

import config
from core.applicant import JobApplicant
from core.browser import human_delay
from core.db import record_application, should_skip_job

_CARD_SELECTORS = [
    "li[data-occludable-job-id]",
    "[data-occludable-job-id]",
    "li[data-job-id]",
    "[data-job-id]",
    ".jobs-search-results__list-item",
    ".job-card-container",
    ".scaffold-layout__list-item",
]

_LOGIN_URL_PARTS = ("/login", "/authwall", "/uas/", "/checkpoint/")


async def _is_linkedin_login_page(page: Page) -> bool:
    url = (page.url or "").lower()
    if any(p in url for p in _LOGIN_URL_PARTS):
        return True
    try:
        if await page.locator("input#username, input#session_key, form.login__form").count() > 0:
            return True
    except Exception:
        pass
    return False


async def _wait_for_job_cards(page: Page, timeout_ms: int = 25_000) -> tuple[int, str]:
    """Return (card count, selector used). Waits for any known job-card selector."""
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        if await _is_linkedin_login_page(page):
            return 0, "login"
        for sel in _CARD_SELECTORS:
            try:
                loc = page.locator(sel)
                n = await loc.count()
                if n > 0:
                    return n, sel
            except Exception:
                continue
        await asyncio.sleep(0.8)
    return 0, ""


def _parse_card_lines(text: str) -> tuple[str, str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    skip_pat = re.compile(
        r"^(viewed|promoted|easy apply|applied|remote|hybrid|on-site|"
        r"\d+\s*(day|hour|week|minute)|with verification|.*\blogo\b)",
        re.I,
    )
    clean = []
    for ln in lines:
        if skip_pat.search(ln):
            continue
        ln = re.sub(r"\s+with verification\s*$", "", ln, flags=re.I).strip()
        ln = re.sub(r"\s+logo\s*$", "", ln, flags=re.I).strip()
        if len(ln) > 2:
            clean.append(ln)
    title = clean[0] if clean else "Unknown"
    company = clean[1] if len(clean) > 1 else "Unknown"
    if company == title and len(clean) > 2:
        company = clean[2]
    return title, company


def _is_experience_mismatch(title: str, card_text: str = "") -> bool:
    """Skip senior / high-experience roles; keep 0-1 year / fresher / junior fits."""
    text = f"{title} {card_text}".lower()

    high_exp = [
        r"\b([6-9]|1[0-9])\+\s*(yrs?|years)\b",
        r"\b([6-9]|1[0-9])\s*(\+|plus)?\s*(yrs?|years)\s*(exp|experience)?\b",
        r"\b([4-9]|1[0-9])-[0-9]+\s*(yrs?|years)\b",
        r"\b(senior|sr\.?|staff|principal|lead|director|manager|architect|head of|sde\s*iii|engineer\s*iii|iii\b)\b",
        r"\b(5\+|6\+|7\+|8\+|10\+)\b",
        r"\b([6-9]|1[0-9])\+\s*yrs?\s*exp\b",
    ]
    for pat in high_exp:
        if re.search(pat, text):
            return True
    return False


def _is_main_career_role(title: str) -> bool:
    """Prefer full-time junior/associate tech roles that advance the career."""
    t = title.lower()
    # Skip pure short internships unless they are clearly SE/AI/ML/FS
    if re.search(r"\bintern(ship)?\b", t):
        if re.search(
            r"\b(software|ai|ml|machine learning|full[\s-]?stack|python|data scientist|sde|android|flutter|mobile|react|frontend|backend|developer)\b",
            t,
        ):
            return True
        return False
    main = [
        r"\bassociate software\b",
        r"\bjunior software\b",
        r"\bsoftware engineer\b",
        r"\bsoftware developer\b",
        r"\bai engineer\b",
        r"\bartificial intelligence\b",
        r"\bml engineer\b",
        r"\bmachine learning engineer\b",
        r"\bmachine learning\b",
        r"\bfull[\s-]?stack\b",
        r"\bpython developer\b",
        r"\bbackend\b",
        r"\bfront[\s-]?end\b",
        r"\bdata analyst\b",
        r"\bdata scientist\b",
        r"\bdata engineer\b",
        r"\breact developer\b",
        r"\bnode\.?js\b",
        r"\bgraduate engineer trainee\b",
        r"\bentry[\s-]?level software\b",
        r"\bjunior (python|data|full|software|developer)\b",
        r"\bnlp\b",
        r"\bllm\b",
        r"\bgenai\b",
        r"\bgenerative ai\b",
        r"\bdeveloper\b",
        r"\bprogrammer\b",
        r"\bsde\b",
        r"\bswe\b",
        r"\bfounding engineer\b",
        r"\bassociate engineer\b",
        r"\bjunior developer\b",
    ]
    return any(re.search(p, t) for p in main)


def _fits_resume(title: str, whitelist: list[str]) -> bool:
    """Require a technical keyword from the resume domain (not just 'intern')."""
    t = title.lower()
    tech_patterns = [
        r"\bsoftware\b",
        r"\bpython\b",
        r"\bmachine learning\b",
        r"\bartificial intelligence\b",
        r"\bai[-/ ]",
        r"[-/ ]ai\b",
        r"^ai\b",
        r"\bml[-/ ]",
        r"[-/ ]ml\b",
        r"^ml\b",
        r"\bdata science\b",
        r"\bdata analyst\b",
        r"\bdata engineer\b",
        r"\bfull[\s-]?stack\b",
        r"\breact\b",
        r"\bangular\b",
        r"\bfastapi\b",
        r"\bbackend\b",
        r"\bfront[\s-]?end\b",
        r"\bprogrammer\b",
        r"\bdata scientist\b",
        r"\bnlp\b",
        r"\bllm\b",
        r"\bdeep learning\b",
        r"\bcomputer vision\b",
        r"\bweb developer\b",
        r"\bapp developer\b",
        r"\bangular\b",
        r"\bvue\b",
        r"\bandroid\b",
        r"\bflutter\b",
        r"\bdeveloper\b",
        r"\bsoftware developer\b",
        r"\bpython developer\b",
        r"\bfull[\s-]?stack developer\b",
        r"\bsde\b",
        r"\bswe\b",
        r"\bcoding\b",
        r"\bdevops\b",
        r"\bgenai\b",
        r"\bgenerative ai\b",
        r"\bsoftware engineer\b",
        r"\bai engineer\b",
        r"\bml engineer\b",
        r"\bmachine learning engineer\b",
        r"\bintern\b.*\b(software|python|ai|ml|data|full.?stack|web|developer)\b",
        r"\b(software|python|ai|ml|data|full.?stack|web|developer).*\bintern\b",
    ]
    reject = [
        r"\bwordpress\b",
        r"\bshopify\b",
        r"\bcnc\b",
        r"\bnumerical control\b",
        r"\baptitude trainer\b",
        r"\bdiploma engineer\b",
        r"\bchemical\b",
        r"\bcampus ambassador\b",
        r"\bhuman resource\b",
        r"\bhr intern\b",
        r"\bms dynamics\b",
        r"\bcrm developer\b",
        r"\binstructor\b",
        r"\btrainer\b",
        r"\bgtm\b",
    ]
    if any(re.search(p, t) for p in reject):
        return False
    if any(re.search(p, t) for p in tech_patterns):
        return True
    for w in whitelist:
        wl = w.lower().strip()
        if wl in (
            "fresher",
            "entry level",
            "junior",
            "intern",
            "trainee",
            "associate",
            "graduate",
            "0-1",
            "1 year",
            "ai",
            "ml",
        ):
            continue
        if wl and re.search(rf"\b{re.escape(wl)}\b", t):
            return True
    return False


async def apply_from_easy_apply_search(
    page: Page,
    applicant: JobApplicant,
    resume: dict[str, Any],
    max_apps: int,
) -> list[dict[str, Any]]:
    prefs = resume.get("job_preferences", {})
    titles = prefs.get("titles", ["Software Engineer"])
    locations = prefs.get("locations", ["Bangalore", "Remote"])
    blacklist = [bk.lower() for bk in prefs.get("blacklist_keywords", [])]
    whitelist = prefs.get("whitelist_keywords", [])
    applied: list[dict[str, Any]] = []
    seen: set[str] = set()

    for title in titles:
        if len(applied) >= max_apps:
            break
        for loc in locations:
            if len(applied) >= max_apps:
                break

            await applicant._close_easy_apply_modal(page)
            url = (
                "https://www.linkedin.com/jobs/search/"
                f"?keywords={quote_plus(title)}&location={quote_plus(loc)}"
                f"&geoId=102713980&f_AL=true&f_TPR=r2592000&sortBy=DD"
            )
            if loc.lower() == "remote" or prefs.get("remote_only"):
                url += "&f_WT=2"
            elif prefs.get("hybrid_only"):
                url += "&f_WT=3"
            logger.info("Easy Apply search: '{}' in '{}'", title, loc)
            try:
                if page.is_closed():
                    logger.error("Browser page closed — stopping search loop")
                    return applied
                await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            except Exception as exc:
                msg = str(exc).lower()
                logger.warning("Search failed: {}", exc)
                closed = False
                try:
                    closed = page.is_closed()
                except Exception:
                    closed = True
                if (
                    closed
                    or "has been closed" in msg
                    or "target closed" in msg
                    or "browser has been closed" in msg
                ):
                    logger.error("Browser/page closed — stopping search loop")
                    return applied
                continue
            await human_delay(2.5, 4)

            if await _is_linkedin_login_page(page):
                logger.warning(
                    "LinkedIn login required on search page ({}) — log in in the browser",
                    page.url[:80],
                )
                continue

            n, card_sel = await _wait_for_job_cards(page)
            if n == 0 and card_sel == "login":
                logger.warning("LinkedIn login wall — skipping search until you log in")
                continue
            if n == 0:
                logger.info(
                    "Found 0 cards on search page ({})",
                    (page.url or "")[:90],
                )
                continue

            cards = page.locator(card_sel)
            # Scroll results list to load more cards
            try:
                list_pane = page.locator(
                    ".jobs-search-results-list, .scaffold-layout__list"
                ).first
                for _ in range(6):
                    if await list_pane.count() > 0:
                        await list_pane.evaluate("e => e.scrollBy(0, 1200)")
                        await human_delay(0.8, 1.2)
                n = await cards.count()
            except Exception:
                pass
            logger.info("Found {} cards on search page", n)
            if n == 0:
                continue

            # Build queue from this search, then apply immediately
            batch: list[dict[str, Any]] = []
            for i in range(min(n, 40)):
                if len(batch) >= 40:
                    break
                card = cards.nth(i)
                try:
                    jid_raw = (
                        await card.get_attribute("data-job-id")
                        or await card.get_attribute("data-occludable-job-id")
                        or ""
                    )
                    jid = re.sub(r"[^\d].*", "", jid_raw.strip().split(",")[0])
                    if not jid or jid in seen or should_skip_job("linkedin", jid):
                        continue
                    row = ((await card.inner_text()) or "")
                    row_l = row.lower()
                    if re.search(r"(?<![a-z])applied(?![a-z])", row_l):
                        continue
                    # Prefer structured title/company from card DOM (inner_text often blank/noisy)
                    job_title, company = _parse_card_lines(row)
                    try:
                        t_el = card.locator(
                            "a.job-card-list__title--link, "
                            "a.job-card-container__link, "
                            ".job-card-list__title, "
                            ".artdeco-entity-lockup__title a, "
                            ".artdeco-entity-lockup__title"
                        ).first
                        if await t_el.count() > 0:
                            t_txt = (
                                (await t_el.inner_text())
                                or (await t_el.get_attribute("aria-label"))
                                or ""
                            ).strip().split("\n")[0]
                            if len(t_txt) > 2:
                                job_title = t_txt
                        c_el = card.locator(
                            ".job-card-container__primary-description, "
                            ".artdeco-entity-lockup__subtitle, "
                            ".job-card-container__company-name"
                        ).first
                        if await c_el.count() > 0:
                            c_txt = ((await c_el.inner_text()) or "").strip().split("\n")[0]
                            if len(c_txt) > 1:
                                company = c_txt
                    except Exception:
                        pass

                    # Unknown titles: still queue — detail pane will resolve + filter
                    if job_title.lower() not in ("unknown", "", "?"):
                        if any(bk in job_title.lower() for bk in blacklist):
                            continue
                        if _is_experience_mismatch(job_title, row_l):
                            logger.info("Skip high-exp role: {}", job_title)
                            continue
                        if not _fits_resume(job_title, whitelist):
                            logger.info("Skip non-fit role: {}", job_title)
                            continue
                        if not _is_main_career_role(job_title):
                            logger.info("Skip non-career-track role: {}", job_title)
                            continue
                    if loc.lower() == "remote" or prefs.get("remote_only"):
                        if not any(
                            k in row_l
                            for k in ("remote", "work from home", "wfh", "anywhere")
                        ):
                            logger.info("Skip non-remote role: {}", job_title)
                            continue
                        if any(k in row_l for k in ("on-site", "onsite", "on site")):
                            if "remote" not in row_l:
                                logger.info("Skip on-site role: {}", job_title)
                                continue
                    elif prefs.get("hybrid_only"):
                        if "hybrid" not in row_l:
                            logger.info("Skip non-hybrid role: {}", job_title)
                            continue
                        if any(
                            k in row_l
                            for k in ("remote", "work from home", "wfh", "anywhere")
                        ) and "hybrid" not in row_l:
                            logger.info("Skip remote-only role: {}", job_title)
                            continue
                    seen.add(jid)
                    batch.append(
                        {
                            "source": "linkedin",
                            "job_id": jid,
                            "title": job_title,
                            "company": company,
                            "location": loc,
                            "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                            "easy_apply": True,
                            "ai_score": 80,
                        }
                    )
                except Exception:
                    continue

            logger.info("Applying from batch of {} jobs (need {})", len(batch), max_apps - len(applied))

            for job in batch:
                if len(applied) >= max_apps:
                    break
                jid = str(job["job_id"])
                job_title = job.get("title", "?")
                company = job.get("company", "?")
                logger.info("→ Applying (job view): {} at {} [{}]", job_title, company, jid)

                try:
                    if page.is_closed():
                        logger.error("Browser page closed — stopping apply loop")
                        return applied

                    await applicant._close_easy_apply_modal(page)
                    # Search split-view first — Easy Apply button is most reliable here
                    navigated = False
                    for url in (
                        "https://www.linkedin.com/jobs/search/"
                        f"?currentJobId={jid}&f_AL=true&geoId=102713980&sortBy=DD",
                        f"https://www.linkedin.com/jobs/view/{jid}/",
                    ):
                        try:
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            navigated = True
                            break
                        except Exception as nav_exc:
                            if page.is_closed():
                                logger.error("Browser closed during navigation — stopping")
                                return applied
                            logger.warning("Nav retry needed for {}: {}", jid, nav_exc)
                    if not navigated:
                        raise RuntimeError(f"Could not open job {jid}")
                    await human_delay(2.5, 4)

                    detail = page.locator(
                        ".jobs-details, .scaffold-layout__detail, .jobs-search__job-details, "
                        ".job-view-layout, .jobs-details__main-content, "
                        ".jobs-unified-top-card, .job-details-jobs-unified-top-card"
                    ).first
                    try:
                        await page.wait_for_function(
                            """() => {
                                const d = document.querySelector(
                                  '.jobs-details, .scaffold-layout__detail, .jobs-search__job-details, ' +
                                  '.job-view-layout, .jobs-details__main-content, main'
                                );
                                if (!d) return false;
                                const loader = d.querySelector('.jobs-loader');
                                if (loader && loader.offsetParent !== null) return false;
                                return [...d.querySelectorAll('button,[role="button"]')].some(b => {
                                  const t = ((b.innerText||'')+' '+(b.getAttribute('aria-label')||'')).toLowerCase();
                                  return t.includes('easy apply') || t.includes('apply') || t.includes('applied');
                                });
                            }""",
                            timeout=18_000,
                        )
                    except Exception:
                        await human_delay(2, 3)

                    try:
                        t_el = detail.locator(
                            "h1, .job-details-jobs-unified-top-card__job-title"
                        )
                        if await t_el.count() > 0:
                            job["title"] = (
                                await t_el.first.inner_text()
                            ).strip().split("\n")[0]
                            job_title = job["title"]
                        c_el = detail.locator(
                            ".job-details-jobs-unified-top-card__company-name a, "
                            ".job-details-jobs-unified-top-card__company-name"
                        )
                        if await c_el.count() > 0:
                            job["company"] = (
                                await c_el.first.inner_text()
                            ).strip().split("\n")[0]
                            company = job["company"]
                    except Exception:
                        pass

                    if any(bk in job_title.lower() for bk in blacklist):
                        logger.info("Skip blacklisted: {}", job_title)
                        continue
                    if _is_experience_mismatch(job_title):
                        logger.info("Skip high-exp role: {}", job_title)
                        continue
                    if not _fits_resume(job_title, whitelist):
                        logger.info("Skip non-fit role: {}", job_title)
                        continue
                    if not _is_main_career_role(job_title):
                        logger.info("Skip non-career-track role: {}", job_title)
                        continue

                    found = await applicant._find_easy_apply_button(
                        page, scope=detail, timeout_s=16
                    )
                    if found == "applied":
                        record_application(job, "skipped", "already applied")
                        continue
                    if found == "external" or found is None:
                        off = await page.get_by_text(
                            re.compile(r"Responses managed off LinkedIn", re.I)
                        ).count()
                        if off > 0 or found == "external":
                            logger.info("Skip external: {} at {}", job_title, company)
                            record_application(job, "external", "external apply")
                        else:
                            logger.info("No Easy Apply: {} at {}", job_title, company)
                            record_application(
                                job, "failed", "Easy Apply button not found"
                            )
                        continue

                    if found != "js_clicked":
                        try:
                            await found.click(timeout=5_000)
                        except Exception:
                            await found.click(force=True, timeout=5_000)
                    await human_delay(1.8, 2.8)

                    result = await applicant._complete_easy_apply_modal(page, jid)
                    if result.status != "applied":
                        await applicant._close_easy_apply_modal(page)

                    job["apply_status"] = result.status
                    job["apply_message"] = result.message
                    record_application(job, result.status, result.message)

                    if result.status == "applied":
                        applied.append(job)
                        logger.info("✓ Applied to {} at {}", job_title, company)
                    else:
                        logger.warning(
                            "✗ {} — {}: {}", result.status, job_title, result.message
                        )

                    delay = random.uniform(
                        config.DELAY_BETWEEN_APPS_MIN,
                        config.DELAY_BETWEEN_APPS_MAX,
                    )
                    logger.info("Waiting {:.0f}s…", delay)
                    await asyncio.sleep(delay)
                except Exception as exc:
                    msg = str(exc).lower()
                    logger.warning("Apply error for {}: {}", jid, exc)
                    closed = False
                    try:
                        closed = page.is_closed()
                    except Exception:
                        closed = True
                    if (
                        closed
                        or "has been closed" in msg
                        or "target closed" in msg
                        or "browser has been closed" in msg
                    ):
                        logger.error("Browser/page closed — stopping apply loop")
                        return applied
                    try:
                        await applicant._close_easy_apply_modal(page)
                    except Exception:
                        pass
                    continue

            # Keep searching until max_apps is reached (do not stop after first hits)
            if len(applied) >= max_apps:
                break
        if len(applied) >= max_apps:
            break

    return applied
