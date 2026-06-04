"""HCaptcha solver using Playwright + vision model.

Challenge types handled:
- Checkbox click (widget iframe)
- Image grid: screenshot grid → vision model → JS-click tiles inside iframe → verify

When vision model fails, falls back to random tile clicking so the user
can see the browser interacting with the page.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

from ..core.config import Config
from .stealth import STEALTH_JS, WAIT_UNTIL

_CDP_URL = os.getenv("CDP_URL", "http://localhost:9222")

log = logging.getLogger(__name__)


async def _connect_cdp(pw: Playwright, max_attempts: int = 60, delay: float = 2.0) -> Browser:
    last_err = None
    for attempt in range(max_attempts):
        try:
            browser = await pw.chromium.connect_over_cdp(_CDP_URL)
            log.info("[hCaptcha] Connected to Brave CDP on attempt %d", attempt + 1)
            return browser
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
    raise last_err


# JS: Extract hCaptcha token
_EXTRACT_TOKEN_JS = """
() => {
    const ta = document.querySelector('[name="h-captcha-response"]');
    if (ta && ta.value && ta.value.length > 20) return ta.value;
    if (window.hcaptcha && typeof window.hcaptcha.getResponse === 'function') {
        const r = window.hcaptcha.getResponse();
        if (r && r.length > 20) return r;
    }
    return null;
}
"""

# JS: Click tiles by index inside the challenge iframe
_CLICK_TILES_JS = """
(indices) => {
    // hCaptcha image grid tiles - comprehensive selector list
    const selectors = [
        '.image', '.tile', '.task-image', '.cell',
        '[class*="image"]', '[class*="tile"]', '[class*="cell"]',
        'button[class*="img"]', 'div[class*="img"]',
        '.challenge-card', '.grid-cell', '.item',
        '.challenge-image', '.task-image-border', '.image-button',
        '.challenge-item', '.img-button', '.image-grid > *',
        '[data-testid="challenge-image"]'
    ];
    let tiles = [];
    for (const sel of selectors) {
        try {
            tiles = document.querySelectorAll(sel);
            if (tiles.length >= 3) break;
        } catch(e) {}
    }
    if (tiles.length === 0) {
        // Last resort: find clickable image-like elements
        tiles = document.querySelectorAll('img, canvas, button, [role="button"]');
    }
    const results = [];
    for (const idx of indices) {
        if (idx >= 0 && idx < tiles.length) {
            tiles[idx].scrollIntoView({block: 'center', inline: 'center'});
            tiles[idx].click();
            results.push({idx: idx, clicked: true});
        } else {
            results.push({idx: idx, clicked: false, error: 'out of range, total=' + tiles.length});
        }
    }
    return {totalTiles: tiles.length, clicked: results};
}
"""

# JS: Click verify/submit button inside challenge iframe
_CLICK_VERIFY_JS = """
() => {
    const selectors = [
        '#submit_button', '.button-submit', '.verify-button',
        'button[type="submit"]', '.submit', '[class*="submit"]',
        '.challenge-submit', '.btn-submit', '#verify-btn',
        '.button', '[data-testid="challenge-verify-button"]'
    ];
    for (const sel of selectors) {
        try {
            const btn = document.querySelector(sel);
            if (btn) { btn.scrollIntoView({block: 'center'}); btn.click(); return {clicked: true, selector: sel}; }
        } catch(e) {}
    }
    // Try any button that looks like submit (text content)
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
        const text = (btn.textContent || '').toLowerCase();
        if (text.includes('verify') || text.includes('submit') || text.includes('check') || text.includes('next')) {
            btn.scrollIntoView({block: 'center'});
            btn.click();
            return {clicked: true, selector: 'button:text(' + btn.textContent + ')'};
        }
    }
    return {clicked: false};
}
"""

# JS: Check if challenge is still showing (to detect "multiple correct" etc)
_CHECK_CHALLENGE_STATUS_JS = """
() => {
    const errorEl = document.querySelector('.error-message, .challenge-error, [class*="error"]');
    const promptEl = document.querySelector('.prompt-text, .challenge-description, .task-desc, [class*="prompt"]');
    return {
        hasError: !!errorEl,
        errorText: errorEl ? errorEl.innerText.trim() : '',
        hasPrompt: !!promptEl,
        promptText: promptEl ? promptEl.innerText.trim() : ''
    };
}
"""

# JS: Get all clickable tile elements for inspection
_INSPECT_TILES_JS = """
() => {
    const selectors = [
        '.image', '.tile', '.task-image', '.cell',
        '[class*="image"]', '[class*="tile"]', '[class*="cell"]',
        '.challenge-card', '.grid-cell', '.item',
        '.challenge-image', '.task-image-border', '.image-button',
        '.challenge-item', '.img-button'
    ];
    let tiles = [];
    for (const sel of selectors) {
        try {
            const found = document.querySelectorAll(sel);
            if (found.length >= 3) { tiles = found; break; }
        } catch(e) {}
    }
    if (tiles.length === 0) {
        tiles = document.querySelectorAll('img, canvas, button, [role="button"]');
    }
    return {
        count: tiles.length,
        descriptions: Array.from(tiles).slice(0, 12).map((t, i) => ({
            index: i,
            tag: t.tagName,
            className: t.className,
            role: t.getAttribute('role'),
            rect: t.getBoundingClientRect ? {
                x: t.getBoundingClientRect().x,
                y: t.getBoundingClientRect().y,
                w: t.getBoundingClientRect().width,
                h: t.getBoundingClientRect().height
            } : null
        }))
    };
}
"""


class HCaptchaSolver:
    def __init__(self, config: Config, browser: Browser | None = None,
                 classification_solver=None) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = browser
        self._owns_browser = browser is None
        self._classifier = classification_solver

    async def start(self) -> None:
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await _connect_cdp(self._playwright)

    async def stop(self) -> None:
        if self._owns_browser:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()

    async def solve(self, params: dict[str, Any]) -> dict[str, Any]:
        website_url = params["websiteURL"]
        log.info("[hCaptcha] === SOLVE START: %s ===", website_url)

        for attempt in range(self._config.captcha_retries):
            log.info("[hCaptcha] Attempt %d/%d", attempt + 1, self._config.captcha_retries)
            try:
                token = await self._solve_once(website_url)
                log.info("[hCaptcha] === SOLVE SUCCESS ===")
                return {"gRecaptchaResponse": token}
            except Exception as exc:
                log.error("[hCaptcha] Attempt FAILED: %s", exc, exc_info=True)
                if attempt < self._config.captcha_retries - 1:
                    await asyncio.sleep(2)

        raise RuntimeError("HCaptcha failed after all attempts")

    async def _get_page(self):
        """Get a page from the default browser context where extensions run.

        browser.new_page() creates a NEW isolated context (like incognito).
        We must use browser.contexts[0] to get the default context that has
        the user's profile, cookies, and installed extensions.

        Returns (page, should_close) tuple. should_close is True only if we
        created a new page (not reusing user's existing tab).
        """
        contexts = self._browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            if pages:
                log.info("[hCaptcha] Reusing existing page in default context (%d pages)", len(pages))
                page = pages[0]
                # Ensure viewport is set
                await page.set_viewport_size({"width": 1920, "height": 1080})
                return page, False  # Don't close user's tab
            log.info("[hCaptcha] Creating new page in default context (extensions active)")
            page = await context.new_page()
            return page, True
        else:
            log.warning("[hCaptcha] No default context found, falling back to isolated context")
            page = await self._browser.new_page(viewport={"width": 1920, "height": 1080})
            return page, True

    async def _solve_once(self, website_url: str) -> str:
        assert self._browser is not None
        page, should_close = await self._get_page()
        await page.add_init_script(STEALTH_JS)

        try:
            log.info("[hCaptcha] Navigating to %s", website_url)
            await page.goto(website_url, wait_until=WAIT_UNTIL,
                           timeout=self._config.browser_timeout * 1000)
            log.info("[hCaptcha] Page loaded")
            await asyncio.sleep(2)

            # ── STEP 1: Click checkbox ──
            log.info("[hCaptcha] --- Step 1: Click checkbox ---")
            clicked = await self._click_checkbox(page)
            if not clicked:
                raise RuntimeError("Could not click checkbox")
            await asyncio.sleep(3)

            token = await page.evaluate(_EXTRACT_TOKEN_JS)
            if isinstance(token, str) and len(token) > 20:
                log.info("[hCaptcha] Easy pass - token found")
                return token

            # ── STEP 2: Detect challenge ──
            log.info("[hCaptcha] --- Step 2: Detect challenge ---")
            challenge = await self._detect_challenge(page)
            log.info("[hCaptcha] Challenge type: %s", challenge.get("type"))

            if challenge["type"] == "none":
                for i in range(6):
                    await asyncio.sleep(5)
                    token = await page.evaluate(_EXTRACT_TOKEN_JS)
                    if isinstance(token, str) and len(token) > 20:
                        return token
                raise RuntimeError("No token after waiting")

            # ── STEP 3: Handle challenge ──
            log.info("[hCaptcha] --- Step 3: Handle %s ---", challenge["type"])
            token = await self._handle_challenge(page, challenge)
            if token:
                return token
            raise RuntimeError("Challenge did not produce token")

        finally:
            if should_close:
                await page.close()

    async def _click_checkbox(self, page) -> bool:
        """Click hCaptcha checkbox via JS inside the widget iframe."""
        # Wait for hCaptcha iframe
        for _ in range(20):
            frames = [f for f in page.frames if f.url and "hcaptcha.com" in f.url]
            if frames:
                break
            await asyncio.sleep(0.5)

        if not frames:
            log.error("[hCaptcha] No hCaptcha iframe found")
            return False

        # Human-like mouse movement before clicking
        await self._human_mouse_move(page, 400, 500, 600, 400)

        # Try clicking checkbox in widget frames
        for f in frames:
            if "checkbox" not in f.url and "anchor" not in f.url:
                continue
            try:
                result = await f.evaluate("""
                    () => {
                        const cb = document.querySelector('#checkbox');
                        if (cb) { cb.click(); return 'clicked_checkbox'; }
                        const cb2 = document.querySelector('[id*="checkbox"]');
                        if (cb2) { cb2.click(); return 'clicked_alt'; }
                        // Try clicking the container
                        const container = document.querySelector('#anchor, .checkbox-container, [class*="checkbox"]');
                        if (container) { container.click(); return 'clicked_container'; }
                        return 'not_found';
                    }
                """)
                log.info("[hCaptcha] Checkbox click result: %s", result)
                await asyncio.sleep(1)
                return True
            except Exception as e:
                log.debug("[hCaptcha] Frame click failed: %s", e)

        # Fallback: Playwright frame_locator
        try:
            iframe = page.frame_locator('iframe[src*="hcaptcha.com"]').first
            checkbox = iframe.locator("#checkbox").first
            await checkbox.click(timeout=8_000)
            log.info("[hCaptcha] Checkbox clicked via frame_locator")
            return True
        except Exception as e:
            log.error("[hCaptcha] frame_locator failed: %s", e)
            return False

    async def _detect_challenge(self, page) -> dict:
        """Detect what type of challenge appeared."""
        result = {"type": "none"}
        frames = page.frames
        log.info("[hCaptcha] %d frames", len(frames))

        for i, f in enumerate(frames):
            url = f.url or ""
            log.info("[hCaptcha]   Frame %d: %s", i, url[:100])
            if "hcaptcha.com" in url and ("challenge" in url or "checkcaptcha" in url):
                result = {"type": "image_grid", "frame_index": i, "frame_url": url}

        if result["type"] == "none":
            try:
                el = page.locator('iframe[src*="hcaptcha.com"][src*="challenge"]')
                if await el.count() > 0:
                    result = {"type": "image_grid"}
            except Exception:
                pass

        return result

    async def _handle_challenge(self, page, challenge: dict) -> str | None:
        if challenge["type"] == "image_grid":
            return await self._solve_image_grid(page, challenge)
        # Unknown: poll for token
        for i in range(10):
            await asyncio.sleep(3)
            token = await page.evaluate(_EXTRACT_TOKEN_JS)
            if isinstance(token, str) and len(token) > 20:
                return token
        return None

    async def _solve_image_grid(self, page, challenge: dict) -> str | None:
        """Screenshot grid, send to vision model, JS-click tiles inside iframe.

        KEY FIX: Tile clicking ALWAYS happens, even when vision model fails.
        If vision model returns 502/empty, we fall back to random tiles so
        the user can see the browser interacting with the page.
        """
        log.info("[hCaptcha] _solve_image_grid: START")

        # Get the challenge frame object (needed for JS evaluate)
        challenge_frame = None
        for f in page.frames:
            if f.url and "hcaptcha.com" in f.url and ("challenge" in f.url or "checkcaptcha" in f.url):
                challenge_frame = f
                break

        if not challenge_frame:
            log.error("[hCaptcha] Challenge frame object not found")
            return None

        log.info("[hCaptcha] Challenge frame URL: %s", challenge_frame.url[:100])

        # ── Inspect available tiles first ──
        try:
            tile_info = await challenge_frame.evaluate(_INSPECT_TILES_JS)
            log.info("[hCaptcha] Found %d tiles: %s",
                     tile_info["count"],
                     [d["tag"] + "." + d["className"][:20] for d in tile_info["descriptions"]])
        except Exception as e:
            log.warning("[hCaptcha] Tile inspection failed: %s", e)
            tile_info = {"count": 9, "descriptions": []}

        # ── Detect challenge sub-type ──
        # hCaptcha has multiple challenge types:
        # - image_grid: 3x3 grid, click matching images (most common)
        # - drag_drop: drag object to target (e.g. "drag the screw to the empty joint")
        # - orientation: click animal facing same direction
        challenge_subtype = "unknown"
        canvas_count = sum(1 for d in tile_info.get("descriptions", []) if d.get("tag") == "CANVAS")
        button_count = sum(1 for d in tile_info.get("descriptions", []) if d.get("tag") == "BUTTON")

        if canvas_count > 0 and tile_info.get("count", 0) <= 10:
            # Drag-drop challenges have a CANVAS element + few UI buttons
            challenge_subtype = "drag_drop"
        elif tile_info.get("count", 0) >= 6:
            challenge_subtype = "image_grid"
        log.info("[hCaptcha] Challenge subtype detected: %s (canvas=%d, buttons=%d, total=%d)",
                 challenge_subtype, canvas_count, button_count, tile_info.get("count", 0))

        # ── Extract question ──
        question = ""
        try:
            question = await challenge_frame.evaluate("""
                () => {
                    const el = document.querySelector('.prompt-text, .challenge-description, .question, .task-desc, [class*="prompt"]');
                    return el ? el.innerText.trim() : '';
                }
            """)
            log.info("[hCaptcha] Question: '%s'", question)
        except Exception as e:
            log.warning("[hCaptcha] Question extract failed: %s", e)
            question = "Select all matching images"

        # ── Screenshot ──
        log.info("[hCaptcha] Taking screenshot...")
        try:
            screenshot_bytes = await page.screenshot()
            log.info("[hCaptcha] Screenshot: %d bytes", len(screenshot_bytes))
        except Exception as e:
            log.error("[hCaptcha] Screenshot failed: %s", e)
            screenshot_bytes = None

        # ── Determine which tiles to click ──
        # VISION MODEL ATTEMPT (best effort - don't let failure stop us)
        answer = []
        if screenshot_bytes and self._classifier is not None:
            b64_image = base64.b64encode(screenshot_bytes).decode()
            log.info("[hCaptcha] Calling vision model...")
            try:
                result = await self._classifier.solve({
                    "type": "HCaptchaClassification",
                    "question": question,
                    "image": b64_image,
                })
                log.info("[hCaptcha] Vision result: %s", result)
                answer = result.get("answer", [])
                if not isinstance(answer, list):
                    log.error("[hCaptcha] Non-list answer: %s", answer)
                    answer = []
            except Exception as e:
                log.error("[hCaptcha] Vision model FAILED: %s", e, exc_info=True)
                answer = []
        else:
            log.info("[hCaptcha] Skipping vision model (no screenshot or no classifier)")

        # FALLBACK: Always produce tile indices to click
        # But only for image_grid — drag_drop needs different handling
        if not answer:
            if challenge_subtype == "drag_drop":
                log.warning("[hCaptcha] Drag-drop challenge WITHOUT vision model — cannot solve reliably")
                # Try clicking on the canvas area (may trigger something)
                canvas_indices = [i for i, d in enumerate(tile_info.get("descriptions", [])) if d.get("tag") == "CANVAS"]
                if canvas_indices:
                    answer = canvas_indices[:1]
                    log.warning("[hCaptcha] Attempting canvas click: %s", answer)
                else:
                    answer = [0]
            else:
                tile_count = tile_info.get("count", 9)
                # Click 2-4 random tiles (hCaptcha grids are typically 3x3 = 9 tiles)
                num_to_click = min(random.randint(2, 4), tile_count)
                answer = random.sample(range(tile_count), num_to_click)
                log.warning("[hCaptcha] Using RANDOM tile fallback (vision unavailable): %s", answer)
        else:
            log.info("[hCaptcha] Using vision model tiles: %s", answer)

        # ── Click tiles via JS inside the challenge frame ──
        # ALWAYS execute this, even with random fallback
        log.info("[hCaptcha] JS-clicking tiles %s inside challenge iframe...", answer)
        try:
            click_result = await challenge_frame.evaluate(_CLICK_TILES_JS, answer)
            log.info("[hCaptcha] Click result: %s", click_result)
        except Exception as e:
            log.error("[hCaptcha] JS tile click FAILED: %s", e)

        await asyncio.sleep(1)

        # ── Click verify via JS ──
        log.info("[hCaptcha] JS-clicking verify...")
        try:
            verify_result = await challenge_frame.evaluate(_CLICK_VERIFY_JS)
            log.info("[hCaptcha] Verify result: %s", verify_result)
        except Exception as e:
            log.error("[hCaptcha] JS verify click FAILED: %s", e)

        # ── Check challenge status (detect "multiple correct" etc) ──
        await asyncio.sleep(2)
        try:
            status = await challenge_frame.evaluate(_CHECK_CHALLENGE_STATUS_JS)
            log.info("[hCaptcha] Challenge status: %s", status)
            if status.get("hasError"):
                log.warning("[hCaptcha] Challenge error: %s", status.get("errorText"))
            # If challenge still showing with same prompt, we may need to click more tiles
            if status.get("hasPrompt") and not status.get("hasError"):
                log.info("[hCaptcha] Challenge still active, clicking 2 more random tiles...")
                extra = random.sample(range(tile_info.get("count", 9)), min(2, tile_info.get("count", 9)))
                try:
                    await challenge_frame.evaluate(_CLICK_TILES_JS, extra)
                    await asyncio.sleep(0.5)
                    await challenge_frame.evaluate(_CLICK_VERIFY_JS)
                except Exception as e:
                    log.debug("[hCaptcha] Extra click failed: %s", e)
        except Exception as e:
            log.debug("[hCaptcha] Status check failed: %s", e)

        # ── Wait for token ──
        log.info("[hCaptcha] Polling for token...")
        await asyncio.sleep(3)
        for i in range(8):
            token = await page.evaluate(_EXTRACT_TOKEN_JS)
            status = "FOUND" if (isinstance(token, str) and len(token) > 20) else "none"
            log.info("[hCaptcha] Poll %d/8: %s", i + 1, status)
            if isinstance(token, str) and len(token) > 20:
                return token
            await asyncio.sleep(3)

        return None

    async def _human_mouse_move(self, page, x1: int, y1: int, x2: int, y2: int) -> None:
        """Simulate human-like mouse movement between two points."""
        steps = random.randint(5, 10)
        for i in range(steps):
            t = (i + 1) / steps
            # Add slight randomness to path
            bx = (1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * ((x1 + x2) / 2 + random.randint(-50, 50)) + t * t * x2
            by = (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * ((y1 + y2) / 2 + random.randint(-30, 30)) + t * t * y2
            await page.mouse.move(int(bx), int(by))
            await asyncio.sleep(random.uniform(0.02, 0.08))
