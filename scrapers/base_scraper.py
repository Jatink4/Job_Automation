"""
scrapers/base_scraper.py — Abstract base class for all site scrapers.

Every site-specific scraper inherits from ``BaseScraper`` and implements
the ``scrape()`` coroutine that returns a list of raw job dicts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from playwright.async_api import Page

from core.browser import BrowserManager


class BaseScraper(ABC):
    """Interface that all scrapers must follow."""

    SOURCE: str = ""  # e.g. "linkedin", "naukri"

    def __init__(self, browser: BrowserManager, resume: dict[str, Any]) -> None:
        self.browser = browser
        self.resume = resume
        self.preferences: dict[str, Any] = resume.get("job_preferences", {})

    @abstractmethod
    async def scrape(self) -> list[dict[str, Any]]:
        """
        Run the full scraping flow and return a list of job dicts.

        Each dict must contain at minimum::

            {
                "source":     str,   # site name
                "job_id":     str,   # unique id on the site
                "title":      str,
                "company":    str,
                "location":   str,
                "url":        str,
                "easy_apply": bool,
                "description": str | None,
            }
        """
        ...

    @abstractmethod
    async def check_session(self, page: Page) -> bool:
        """Return True if the user is logged in, False otherwise."""
        ...
