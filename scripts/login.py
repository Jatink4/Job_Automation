"""
scripts/login.py — One-time Interactive Login Helper for LinkedIn & Naukri.

Launches the persistent Playwright Chromium browser in visible (headed) mode,
opens LinkedIn and Naukri login pages, and waits for you to log in.
All cookies, tokens, and session data are automatically saved to `browser_data/`
so future discovery and application runs stay logged in permanently.

Usage:
    python scripts/login.py
    python main.py --login
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from loguru import logger
import config
from core.browser import BrowserManager, human_delay


async def interactive_login() -> None:
    print("=" * 65)
    print(" 🔑 Interactive Browser Login Helper")
    print("   Target: LinkedIn & Naukri.com")
    print(f"   Profile Storage: {config.BROWSER_DATA_DIR}")
    print("=" * 65)
    print("\nA Chromium browser window will now open.")
    print("1. Log in to LinkedIn (Tab 1) — via Google, email, or your credentials.")
    print("2. Log in to Naukri (Tab 2) — via Google, email, or your credentials.")
    print("3. Once logged in, your session is saved in `browser_data` permanently.")
    print("4. Press ENTER here in the terminal when you are done, or close the browser.\n")

    async with BrowserManager() as browser:
        # Tab 1: LinkedIn
        page_linkedin = await browser.new_page(caller="login_linkedin")
        logger.info("Opening LinkedIn login page...")
        await page_linkedin.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=45_000)

        # Tab 2: Naukri
        page_naukri = await browser.new_page(caller="login_naukri")
        logger.info("Opening Naukri login page...")
        await page_naukri.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded", timeout=45_000)

        # Monitor loop
        print("\n👀 Monitoring login status (checking every 3s)...")
        logged_in_linkedin = False
        logged_in_naukri = False

        for _ in range(100):  # Poll for up to 5 minutes
            await asyncio.sleep(3)

            # Check LinkedIn
            if not logged_in_linkedin and not page_linkedin.is_closed():
                try:
                    url = page_linkedin.url
                    if "/login" not in url and "/authwall" not in url and "/uas/" not in url and "/checkpoint/" not in url:
                        logged_in_linkedin = True
                        logger.success("✓ LinkedIn Login Detected! Session saved.")
                except Exception:
                    pass

            # Check Naukri
            if not logged_in_naukri and not page_naukri.is_closed():
                try:
                    url = page_naukri.url
                    if "/nlogin" not in url and "login" not in url.lower():
                        logged_in_naukri = True
                        logger.success("✓ Naukri Login Detected! Session saved.")
                except Exception:
                    pass

            if logged_in_linkedin and logged_in_naukri:
                logger.success("\n🎉 Both LinkedIn and Naukri are logged in successfully!")
                break

        print("\nPress ENTER to close the browser and save your session...", end="", flush=True)
        # Run input in executor so it doesn't block async loop
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, sys.stdin.readline)
        except Exception:
            pass

    print("\n✓ Browser closed. All session cookies are safely preserved in `browser_data`.")
    print("You can now run discovery with:")
    print("    python main.py --profile all --sites all --dry-run\n")


if __name__ == "__main__":
    asyncio.run(interactive_login())
