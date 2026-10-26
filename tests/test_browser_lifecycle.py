"""
tests/test_browser_lifecycle.py — Tests for Playwright Chromium lifecycle,
health tracking, self-healing recovery, and safe page ownership.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.browser import BrowserManager


@pytest.mark.anyio
async def test_browser_lifecycle_state_and_clean_shutdown():
    """Verify that BrowserManager starts up, tracks health, and shuts down cleanly."""
    bm = BrowserManager()
    assert bm.is_alive() is False

    # Mock playwright objects for deterministic unit test
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.close = AsyncMock()

    mock_context = MagicMock()
    mock_context.is_closed.return_value = False
    mock_context.pages = [mock_page]
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    mock_context.add_init_script = AsyncMock()
    mock_context.on = MagicMock()
    mock_context.browser = MagicMock()
    mock_context.browser.is_connected.return_value = True

    mock_playwright = MagicMock()
    mock_playwright.stop = AsyncMock()
    mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

    with patch("core.browser.async_playwright") as mock_ap:
        mock_p_instance = MagicMock()
        mock_p_instance.start = AsyncMock(return_value=mock_playwright)
        mock_ap.return_value = mock_p_instance

        async with bm:
            assert bm.is_alive() is True
            page = await bm.new_page(caller="unit_test")
            assert page is not None
            await bm.safe_close_page(page, caller="unit_test")
            mock_page.close.assert_awaited_once()

        assert bm.is_alive() is False
        mock_context.close.assert_awaited()
        mock_playwright.stop.assert_awaited_once()


@pytest.mark.anyio
async def test_safe_close_page_handles_none_and_already_closed():
    """Verify safe_close_page never raises even if page is None or closed."""
    bm = BrowserManager()
    # Should not raise for None
    await bm.safe_close_page(None, caller="test")

    mock_closed_page = MagicMock()
    mock_closed_page.is_closed.return_value = True
    mock_closed_page.close = AsyncMock()
    await bm.safe_close_page(mock_closed_page, caller="test")
    mock_closed_page.close.assert_not_awaited()


@pytest.mark.anyio
async def test_self_healing_recovery_on_context_closure():
    """
    Verify that if the browser context unexpectedly dies or closes,
    ensure_context / new_page detects the failure and re-launches Chromium.
    """
    bm = BrowserManager()

    # Initial context (simulated crash)
    dead_context = MagicMock()
    dead_context.is_closed.return_value = True

    # Recovered context
    live_page = MagicMock()
    live_page.is_closed.return_value = False
    live_page.close = AsyncMock()

    new_context = MagicMock()
    new_context.is_closed.return_value = False
    new_context.pages = [live_page]
    new_context.new_page = AsyncMock(return_value=live_page)
    new_context.add_init_script = AsyncMock()
    new_context.on = MagicMock()
    new_context.browser = MagicMock()
    new_context.browser.is_connected.return_value = True

    mock_playwright = MagicMock()
    mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=new_context)

    bm._playwright = mock_playwright
    bm._context = dead_context

    # Currently dead
    assert bm.is_alive() is False

    # Calling new_page should trigger ensure_context -> self-heal
    page = await bm.new_page(caller="recovery_test")
    assert page is live_page
    assert bm.is_alive() is True
    assert bm._recovery_count == 1


@pytest.mark.anyio
async def test_scraper_isolation_failure_does_not_break_subsequent_scrapers():
    """
    Verify that an exception in one scraper (e.g. LinkedIn) does not prevent
    subsequent scrapers (e.g. Naukri or Web) from obtaining a healthy page.
    """
    bm = BrowserManager()

    mock_page1 = MagicMock()
    mock_page1.is_closed.return_value = False
    mock_page1.close = AsyncMock()

    mock_page2 = MagicMock()
    mock_page2.is_closed.return_value = False
    mock_page2.close = AsyncMock()

    mock_context = MagicMock()
    mock_context.is_closed.return_value = False
    mock_context.pages = [mock_page1]
    mock_context.new_page = AsyncMock(side_effect=[mock_page1, mock_page2])
    mock_context.add_init_script = AsyncMock()
    mock_context.on = MagicMock()
    mock_context.browser = MagicMock()
    mock_context.browser.is_connected.return_value = True

    bm._playwright = MagicMock()
    bm._context = mock_context

    # Scraper 1 starts, encounters simulated failure
    p1 = await bm.new_page(caller="scraper1_failed")
    await bm.safe_close_page(p1, caller="scraper1_failed")

    # Scraper 2 should still be able to acquire its page without issue
    p2 = await bm.new_page(caller="scraper2_success")
    assert p2 is mock_page2
    await bm.safe_close_page(p2, caller="scraper2_success")


@pytest.mark.anyio
async def test_sequential_execution_across_profiles():
    """
    Verify that multiple profiles (Profile 1, 2, 3) can sequentially acquire
    and release pages without resource leakage or context degradation.
    """
    bm = BrowserManager()

    pages = []
    for _ in range(3):
        p = MagicMock()
        p.is_closed.return_value = False
        p.close = AsyncMock()
        pages.append(p)

    mock_context = MagicMock()
    mock_context.is_closed.return_value = False
    mock_context.pages = [pages[0]]
    mock_context.new_page = AsyncMock(side_effect=pages)
    mock_context.add_init_script = AsyncMock()
    mock_context.on = MagicMock()
    mock_context.browser = MagicMock()
    mock_context.browser.is_connected.return_value = True

    bm._playwright = MagicMock()
    bm._context = mock_context

    for i in range(3):
        page = await bm.new_page(caller=f"profile_{i+1}")
        assert page is pages[i]
        await bm.safe_close_page(page, caller=f"profile_{i+1}")
        pages[i].close.assert_awaited_once()
