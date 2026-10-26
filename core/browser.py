"""
core/browser.py — Browser lifecycle & human-simulation helpers.

Launches Chromium with a persistent user-data directory so login cookies
survive between runs.  Applies playwright-stealth to minimise bot detection.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from loguru import logger
from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright_stealth import Stealth  # type: ignore[import-untyped]

import config

# Single Stealth instance reused across all pages/contexts
_stealth = Stealth()


# ──────────────────────────────────────────────────────────────────────
#  Custom exceptions
# ──────────────────────────────────────────────────────────────────────
class SessionExpiredError(Exception):
    """Raised when a site redirects to its login page unexpectedly."""


class CaptchaDetectedError(Exception):
    """Raised when a CAPTCHA challenge is detected on the page."""


# ──────────────────────────────────────────────────────────────────────
#  Browser manager (async context-manager)
# ──────────────────────────────────────────────────────────────────────
class BrowserManager:
    """
    Wraps Playwright lifecycle.

    Usage::

        async with BrowserManager() as bm:
            page = await bm.new_page()
            ...
    """

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None

    # ── context-manager protocol ────────────────────────────────────
    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()

        # Randomise viewport dimensions for each run
        viewport_width = random.randint(1280, 1920)
        viewport_height = random.randint(720, 1080)

        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_DATA_DIR),
            headless=False,
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent=random.choice(user_agents),
            locale="en-US",
            timezone_id="Asia/Kolkata",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--disable-background-timer-throttling",
                "--disable-popup-blocking",
                "--disable-prompt-on-repost",
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
                "--disable-default-apps",
                "--window-size={},{}".format(viewport_width, viewport_height),
            ],
            ignore_default_args=["--enable-automation"],
        )

        # Apply stealth to the context so all pages inherit it
        await _stealth.apply_stealth_async(self._context)

        # Extra anti-detection: patch navigator properties on every new page
        async def _apply_extra_stealth(page: Page) -> None:
            try:
                if page.is_closed():
                    return
                await page.add_init_script("""
                    // Remove webdriver flag
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

                    // Fake plugins
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });

                    // Fake languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });

                    // Remove automation indicators from chrome object
                    if (window.chrome) {
                        window.chrome.runtime = { connect: () => {}, sendMessage: () => {} };
                    }

                    // Override permissions query
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) =>
                        parameters.name === 'notifications'
                            ? Promise.resolve({ state: Notification.permission })
                            : originalQuery(parameters);
                """)
            except Exception as exc:
                # New tabs can close before init script attaches; don't crash the run
                logger.debug("Stealth init skipped: {}", exc)

        # Apply to existing pages
        for p in self._context.pages:
            await _apply_extra_stealth(p)

        # Apply to all future pages
        self._context.on("page", lambda p: asyncio.ensure_future(_apply_extra_stealth(p)))

        logger.info(
            "🔴 Browser launched — viewport {}×{}, user-data-dir={}",
            viewport_width,
            viewport_height,
            config.BROWSER_DATA_DIR,
        )
        logger.info("📌 IMPORTANT: A browser window is now open. If you need to log in, the browser will prompt you.")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._context:
            try:
                await self._context.close()
                logger.info("Browser context closed")
            except Exception:
                logger.info("Browser context was already closed")
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    # ── public helpers ──────────────────────────────────────────────
    async def new_page(self) -> Page:
        """Create a brand-new tab. Stealth is applied at context level."""
        assert self._context is not None, "BrowserManager not initialised"
        page = await self._context.new_page()
        return page

    async def get_page(self) -> Page:
        """Return the first existing tab, or create one if none exist."""
        assert self._context is not None, "BrowserManager not initialised"
        pages = self._context.pages
        if pages:
            return pages[0]
        return await self._context.new_page()

    @property
    def context(self) -> BrowserContext:
        assert self._context is not None, "BrowserManager not initialised"
        return self._context


# ──────────────────────────────────────────────────────────────────────
#  Human-simulation helpers  (module-level, work on any Page)
# ──────────────────────────────────────────────────────────────────────


async def human_delay(min_s: float = 0.8, max_s: float = 2.5) -> None:
    """Async sleep for a random duration, simulating human pause."""
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


async def human_type(page: Page, selector: str, text: str) -> None:
    """
    Type *text* into the element matched by *selector*, character by
    character with random inter-key delays (50–150 ms).
    """
    element = page.locator(selector)
    await element.click()
    await human_delay(0.3, 0.6)

    # Clear any existing value first
    await element.fill("")
    for char in text:
        await element.press(char if len(char) == 1 else char)
        await asyncio.sleep(random.uniform(0.05, 0.15))


async def random_scroll(page: Page, min_px: int = 200, max_px: int = 600) -> None:
    """Scroll the page by a random amount (simulates reading)."""
    distance = random.randint(min_px, max_px)
    await page.evaluate(f"window.scrollBy(0, {distance})")
    await human_delay(0.5, 1.5)


async def safe_click(page: Page, selector: str, timeout: int = 10_000) -> None:
    """Click an element, waiting for it to be visible first."""
    await page.wait_for_selector(selector, state="visible", timeout=timeout)
    await human_delay(0.3, 0.8)
    await page.click(selector)


async def check_for_captcha(page: Page) -> bool:
    """
    Return True if common CAPTCHA selectors are detected on the page.
    """
    captcha_selectors = [
        "iframe[src*='captcha']",
        "iframe[src*='recaptcha']",
        "#captcha",
        ".g-recaptcha",
        "[data-captcha]",
        "iframe[src*='hcaptcha']",
        "#px-captcha",                       # PerimeterX
        "iframe[title*='challenge']",
    ]
    for sel in captcha_selectors:
        locator = page.locator(sel)
        # Only consider as CAPTCHA if at least one matching element is visible
        if await locator.is_visible():
            logger.warning("CAPTCHA detected via visible selector '{}'", sel)
            return True
    return False


async def take_screenshot(page: Page, job_id: str) -> str:
    """Save a full-page screenshot and return the file path."""
    path = config.SCREENSHOTS_DIR / f"{job_id}.png"
    await page.screenshot(path=str(path), full_page=True)
    logger.info("Screenshot saved → {}", path)
    return str(path)


async def ensure_google_login(page: Page) -> bool:
    """
    Assists in signing in to Google with the candidate's Gmail account.
    Session and cookies are preserved permanently in browser_data.
    """
    if not config.GMAIL_EMAIL:
        return False

    try:
        await page.goto("https://accounts.google.com", wait_until="domcontentloaded", timeout=30_000)
        await human_delay(1.5, 3.0)

        # Check if already authenticated
        if "myaccount.google.com" in page.url or (await page.locator("a[aria-label*='Google Account']").count()) > 0:
            logger.info("✓ Google session active for {}", config.GMAIL_EMAIL)
            return True

        email_input = page.locator("input[type='email']")
        if await email_input.count() > 0:
            logger.info("Entering Google account: {}", config.GMAIL_EMAIL)
            await email_input.first.fill(config.GMAIL_EMAIL)
            await page.keyboard.press("Enter")
            await human_delay(2.5, 4.0)

        pwd_input = page.locator("input[type='password']")
        if await pwd_input.count() > 0 and config.GMAIL_PASSWORD:
            logger.info("Entering password for Google account...")
            await pwd_input.first.fill(config.GMAIL_PASSWORD)
            await page.keyboard.press("Enter")
            await human_delay(3.0, 5.0)

        logger.info("Google authentication sequence executed.")
        return True
    except Exception as exc:
        logger.debug("Google login automation helper notice: {}", exc)
        return False
