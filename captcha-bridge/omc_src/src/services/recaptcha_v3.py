"""reCAPTCHA v3 solver using Playwright browser automation."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

from ..core.config import Config
from .stealth import STEALTH_JS, WAIT_UNTIL

_CDP_URL = os.getenv("CDP_URL", "http://localhost:9222")

async def _connect_cdp(pw: Playwright, max_attempts: int = 60, delay: float = 2.0) -> Browser:
    """Connect to external Brave/Chromium via CDP with retry."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            browser = await pw.chromium.connect_over_cdp(_CDP_URL)
            log.info("Connected to Brave CDP on attempt %d", attempt + 1)
            return browser
        except Exception as e:
            last_err = e
            log.debug("CDP attempt %d/%d failed: %s", attempt + 1, max_attempts, e)
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
    raise last_err

log = logging.getLogger(__name__)

# JS executed inside the browser to obtain a reCAPTCHA v3 token.
# Handles both standard and enterprise reCAPTCHA libraries.
_EXECUTE_JS = """
([key, action]) => new Promise((resolve, reject) => {
    const gr = window.grecaptcha?.enterprise || window.grecaptcha;
    if (gr && typeof gr.execute === 'function') {
        gr.ready(() => {
            gr.execute(key, {action}).then(resolve).catch(reject);
        });
        return;
    }
    // grecaptcha not loaded yet — inject the script ourselves
    const script = document.createElement('script');
    script.src = 'https://www.google.com/recaptcha/api.js?render=' + key;
    script.onerror = () => reject(new Error('Failed to load reCAPTCHA script'));
    script.onload = () => {
        const g = window.grecaptcha;
        if (!g) { reject(new Error('grecaptcha still undefined after script load')); return; }
        g.ready(() => {
            g.execute(key, {action}).then(resolve).catch(reject);
        });
    };
    document.head.appendChild(script);
})
"""

# Basic anti-detection init script
class RecaptchaV3Solver:
    """Solves RecaptchaV3TaskProxyless tasks via headless Chromium."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await _connect_cdp(self._playwright)
        log.info(
            "Playwright browser started (headless=%s)", self._config.browser_headless
        )

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("Playwright browser stopped")

    async def solve(self, params: dict[str, Any]) -> dict[str, Any]:
        website_url = params["websiteURL"]
        website_key = params["websiteKey"]
        page_action = params.get("pageAction", "verify")

        last_error: Exception | None = None
        for attempt in range(self._config.captcha_retries):
            try:
                token = await self._solve_once(
                    website_url, website_key, page_action
                )
                return {"gRecaptchaResponse": token}
            except Exception as exc:
                last_error = exc
                log.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    self._config.captcha_retries,
                    website_url,
                    exc,
                )
                if attempt < self._config.captcha_retries - 1:
                    await asyncio.sleep(2)

        raise RuntimeError(
            f"Failed after {self._config.captcha_retries} attempts: {last_error}"
        )

    async def _get_page(self):
        """Get a page from the default browser context where extensions run."""
        contexts = self._browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            if pages:
                page = pages[0]
                await page.set_viewport_size({"width": 1920, "height": 1080})
                return page, False
            page = await context.new_page()
            return page, True
        else:
            page = await self._browser.new_page(viewport={"width": 1920, "height": 1080})
            return page, True

    async def _solve_once(
        self, website_url: str, website_key: str, page_action: str
    ) -> str:
        assert self._browser is not None

        page, should_close = await self._get_page()
        await page.add_init_script(STEALTH_JS)

        try:
            timeout_ms = self._config.browser_timeout * 1000
            await page.goto(
                website_url, wait_until=WAIT_UNTIL, timeout=timeout_ms
            )

            # Simulate minimal human-like behaviour to improve score
            await page.mouse.move(400, 300)
            await asyncio.sleep(1)
            await page.mouse.move(600, 400)
            await asyncio.sleep(0.5)

            # Wait for reCAPTCHA to become available (may already be on page)
            try:
                await page.wait_for_function(
                    "(typeof grecaptcha !== 'undefined' && typeof grecaptcha.execute === 'function') "
                    "|| (typeof grecaptcha !== 'undefined' && typeof grecaptcha?.enterprise?.execute === 'function')",
                    timeout=10_000,
                )
            except Exception:
                log.info(
                    "grecaptcha not detected on page, will attempt script injection"
                )

            token = await page.evaluate(_EXECUTE_JS, [website_key, page_action])

            if not isinstance(token, str) or len(token) < 20:
                raise RuntimeError(f"Invalid token received: {token!r}")

            log.info(
                "Got reCAPTCHA token for %s (len=%d)", website_url, len(token)
            )
            return token
        finally:
            if should_close:
                await page.close()
