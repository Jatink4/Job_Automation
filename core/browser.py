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
    Robust Playwright Browser Lifecycle Manager.

    Guarantees:
    - Well-defined lifecycle scope (single context-manager ownership).
    - Health checking and automatic self-healing if Chromium crashes or disconnects.
    - Serialized page creation via asyncio.Lock to prevent CDP protocol race conditions.
    - Independent page ownership per scraper; safe page cleanup without premature context teardown.
    - Context-level init script injection (no unawaited background event handlers).
    - Comprehensive diagnostic logging (startup, page creation, closure, recovery, teardown).
    """

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._lifecycle_lock = asyncio.Lock()
        self._page_lock = asyncio.Lock()
        self._is_shutting_down = False
        self._recovery_count = 0
        self._max_recoveries = 3

    # ── Context Health & State ──────────────────────────────────────
    def is_alive(self) -> bool:
        """Return True if Playwright runtime and browser context are active and responsive."""
        if self._is_shutting_down:
            return False
        if self._playwright is None or self._context is None:
            return False
        try:
            if self._context.is_closed():
                return False
            # If browser object is attached, verify connection
            if self._context.browser is not None and not self._context.browser.is_connected():
                return False
            return True
        except Exception:
            return False

    async def _launch_context(self) -> BrowserContext:
        """Internal helper to initialize Playwright and launch persistent Chromium."""
        if self._playwright is None:
            logger.info("[BrowserManager] Starting Playwright runtime...")
            self._playwright = await async_playwright().start()

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

        logger.info(
            "[BrowserManager] Launching persistent Chromium context (user_data_dir='{}', viewport={}x{})...",
            config.BROWSER_DATA_DIR,
            viewport_width,
            viewport_height,
        )

        # Stable, non-conflicting arguments for Windows persistent context
        stable_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-background-timer-throttling",
            "--disable-popup-blocking",
            "--window-size={},{}".format(viewport_width, viewport_height),
        ]

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.BROWSER_DATA_DIR),
                headless=False,
                viewport={"width": viewport_width, "height": viewport_height},
                user_agent=random.choice(user_agents),
                locale="en-US",
                timezone_id="Asia/Kolkata",
                args=stable_args,
                ignore_default_args=["--enable-automation"],
            )
        except Exception as exc:
            logger.error(
                "[BrowserManager] Failed to launch Chromium persistent context: {}. "
                "Ensure no other process is locking '{}'.",
                exc,
                config.BROWSER_DATA_DIR,
            )
            raise

        # Diagnostic listener for unexpected context closure
        self._context.on("close", lambda ctx: logger.warning("[BrowserManager] Chromium context closed by user or host system."))

        # Apply stealth at context level
        try:
            await _stealth.apply_stealth_async(self._context)
        except Exception as exc:
            logger.debug("[BrowserManager] Stealth initialization notice: {}", exc)

        # Extra anti-detection script attached directly to context (applies cleanly to all future pages via CDP)
        await self._context.add_init_script("""
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

        logger.info(
            "🔴 [BrowserManager] Browser context active (pages: {}, user-data-dir={})",
            len(self._context.pages),
            config.BROWSER_DATA_DIR,
        )
        return self._context

    async def ensure_context(self) -> BrowserContext:
        """
        Verify that the browser context is healthy and responsive.
        If the context or browser process was closed or crashed, automatically re-establishes it.
        """
        async with self._lifecycle_lock:
            if self.is_alive():
                assert self._context is not None
                return self._context

            if self._is_shutting_down:
                raise RuntimeError("[BrowserManager] Cannot create context during manager shutdown")

            if self._recovery_count >= self._max_recoveries:
                raise RuntimeError(
                    f"[BrowserManager] Exceeded maximum recovery attempts ({self._max_recoveries}). "
                    "Chromium cannot be stabilized."
                )

            self._recovery_count += 1
            logger.warning(
                "[BrowserManager] Browser context is closed or disconnected. Self-healing/recovering (attempt {}/{})...",
                self._recovery_count,
                self._max_recoveries,
            )

            # Clean up dead references
            await self._cleanup_context_internal()
            return await self._launch_context()

    async def _cleanup_context_internal(self) -> None:
        """Internal teardown of context without stopping playwright unless required."""
        if self._context:
            try:
                if not self._context.is_closed():
                    await self._context.close()
            except Exception:
                pass
            self._context = None

    # ── Context-manager protocol ────────────────────────────────────
    async def __aenter__(self) -> "BrowserManager":
        async with self._lifecycle_lock:
            self._is_shutting_down = False
            self._recovery_count = 0
            await self._launch_context()
            return self

    async def __aexit__(self, *_exc: object) -> None:
        async with self._lifecycle_lock:
            self._is_shutting_down = True
            logger.info("[BrowserManager] Initiating clean shutdown of browser resources...")

            # 1. Close open pages first
            if self._context and not self._context.is_closed():
                try:
                    for page in list(self._context.pages):
                        if not page.is_closed():
                            await page.close()
                except Exception as exc:
                    logger.debug("[BrowserManager] Error closing pages during teardown: {}", exc)

            # 2. Close persistent context
            if self._context:
                try:
                    if not self._context.is_closed():
                        await self._context.close()
                    logger.info("[BrowserManager] Browser context closed successfully.")
                except Exception as exc:
                    logger.debug("[BrowserManager] Context was already closed: {}", exc)
                self._context = None

            # 3. Stop Playwright runtime
            if self._playwright:
                try:
                    await self._playwright.stop()
                    logger.info("[BrowserManager] Playwright runtime stopped cleanly.")
                except Exception as exc:
                    logger.debug("[BrowserManager] Error stopping Playwright runtime: {}", exc)
                self._playwright = None

    # ── Public Page Helpers ─────────────────────────────────────────
    async def new_page(self, caller: str = "unknown") -> Page:
        """
        Create a new isolated tab for a specific scraper or task.
        Serialized through _page_lock with auto-recovery if the context was closed.
        """
        async with self._page_lock:
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                try:
                    context = await self.ensure_context()
                    logger.debug("[BrowserManager] Opening new tab for '{}' (open tabs: {})", caller, len(context.pages))
                    page = await context.new_page()
                    return page
                except Exception as exc:
                    logger.warning(
                        "[BrowserManager] Failed opening new tab for '{}' on attempt {}/{}: {}",
                        caller,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    # Mark context invalid to trigger recovery on next attempt
                    self._context = None
                    if attempt == max_attempts:
                        logger.error("[BrowserManager] Exhausted page-creation retries for '{}'", caller)
                        raise
                    await asyncio.sleep(1.0)

        raise RuntimeError(f"[BrowserManager] Unable to create tab for '{caller}'")

    async def get_page(self, caller: str = "unknown") -> Page:
        """
        Return an active page for the caller.
        If pages exist and are healthy, returns one; otherwise creates a clean new tab.
        """
        async with self._page_lock:
            context = await self.ensure_context()
            for p in context.pages:
                if not p.is_closed():
                    return p
        return await self.new_page(caller=caller)

    async def safe_close_page(self, page: Optional[Page], caller: str = "unknown") -> None:
        """
        Safely closes a page without raising errors or affecting shared browser context.
        """
        if page is None:
            return
        try:
            if not page.is_closed():
                await page.close()
                logger.debug("[BrowserManager] Closed tab for '{}'", caller)
        except Exception as exc:
            logger.debug("[BrowserManager] Notice while closing tab for '{}': {}", caller, exc)

    @property
    def context(self) -> BrowserContext:
        assert self._context is not None, "BrowserManager context not initialised"
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
