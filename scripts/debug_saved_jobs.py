"""Debug LinkedIn saved-jobs page structure."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from core.browser import BrowserManager, human_delay
from scrapers.linkedin import LinkedInScraper
from config import load_resume


async def main() -> None:
    resume = load_resume()
    async with BrowserManager() as browser:
        scraper = LinkedInScraper(browser, resume)
        page = await browser.get_page()
        if not await scraper.check_session(page):
            print("LOGIN NEEDED — log in then press ENTER")
            await asyncio.get_event_loop().run_in_executor(None, input)

        await page.goto(
            "https://www.linkedin.com/my-items/saved-jobs/",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await human_delay(3, 5)
        out = Path("screenshots")
        out.mkdir(exist_ok=True)
        path = out / "saved_jobs_debug.png"
        await page.screenshot(path=str(path), full_page=True)
        print("URL:", page.url)
        print("TITLE:", await page.title())
        print("SHOT:", path)

        hrefs = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(e => ({href: e.href, text: (e.innerText||'').trim().slice(0,80)}))
               .filter(x => /job/i.test(x.href) || /job/i.test(x.text))
               .slice(0, 40)""",
        )
        print("JOB-LIKE LINKS:", len(hrefs))
        for h in hrefs[:25]:
            print(" -", h)

        # Also dump some class names
        classes = await page.evaluate(
            """() => [...document.querySelectorAll('[class]')].slice(0,200)
               .map(e => e.className).filter(c => /job|saved|entity|result|card/i.test(String(c)))
               .slice(0, 40)"""
        )
        print("CLASSES:", classes)


if __name__ == "__main__":
    asyncio.run(main())
