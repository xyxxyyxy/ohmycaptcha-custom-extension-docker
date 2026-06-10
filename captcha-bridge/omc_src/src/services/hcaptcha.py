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

# JS: Click the refresh button to get a new challenge
_CLICK_REFRESH_JS = """
() => {
    const selectors = [
        '.refresh-button', '#refresh', '[class*="refresh"]',
        'button[title*="refresh" i]', 'button[aria-label*="refresh" i]',
        '.challenge-refresh', '.reload', '.new-challenge'
    ];
    for (const sel of selectors) {
        try {
            const btn = document.querySelector(sel);
            if (btn) { btn.click(); return {clicked: true, selector: sel}; }
        } catch(e) {}
    }
    // Fallback: try title/aria attributes
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
        const title = (btn.getAttribute('title') || '').toLowerCase();
        const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
        if (title.includes('refresh') || title.includes('new') || aria.includes('refresh') || aria.includes('new')) {
            btn.click();
            return {clicked: true, selector: 'button[title/aria=' + (btn.getAttribute('title') || btn.getAttribute('aria-label')) + ']'};
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
        """Solve hCaptcha image grid with challenge retry and refresh.

        Strategy:
        1. Try to solve current challenge (screenshot → vision → click tiles → verify)
        2. If challenge fails or is too difficult, click refresh to get a new one
        3. Retry up to 3 challenges per page visit
        4. Each challenge: vision model suggests tiles, we click them, check result
        """
        log.info("[hCaptcha] _solve_image_grid: START")

        for challenge_attempt in range(3):
            log.info("[hCaptcha] Challenge attempt %d/3", challenge_attempt + 1)

            # Re-locate challenge frame (it may have reloaded after refresh)
            challenge_frame = None
            for _ in range(10):
                for f in page.frames:
                    if f.url and "hcaptcha.com" in f.url and ("challenge" in f.url or "checkcaptcha" in f.url):
                        challenge_frame = f
                        break
                if challenge_frame:
                    break
                await asyncio.sleep(0.5)

            if not challenge_frame:
                log.error("[hCaptcha] Challenge frame not found")
                return None

            log.info("[hCaptcha] Challenge frame URL: %s", challenge_frame.url[:100])

            # ── Inspect tiles ──
            try:
                tile_info = await challenge_frame.evaluate(_INSPECT_TILES_JS)
                log.info("[hCaptcha] Found %d tiles", tile_info["count"])
            except Exception as e:
                log.warning("[hCaptcha] Tile inspection failed: %s", e)
                tile_info = {"count": 9, "descriptions": []}

            # ── Extract question FIRST (needed for subtype detection) ──
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

            # ── Detect challenge sub-type ──
            tile_count = tile_info.get("count", 9)
            canvas_count = sum(1 for d in tile_info.get("descriptions", []) if d.get("tag") == "CANVAS")
            question_lower = question.lower()
            
            is_logic_puzzle = any(kw in question_lower for kw in [
                "wrong", "different", "odd one", "does not belong",
                "facing", "direction", "orientation",
                "match the", "same as", "identical",
            ])
            
            if canvas_count > 0 and tile_count <= 10 and tile_count < 4:
                challenge_subtype = "drag_drop"
            elif tile_count <= 3 and is_logic_puzzle:
                challenge_subtype = "logic_puzzle"  # 1x2 or 1x3 grid
            elif tile_count >= 4:
                challenge_subtype = "image_grid"
            else:
                challenge_subtype = "unknown"
            
            log.info("[hCaptcha] Subtype: %s (tiles=%d, canvas=%d, logic=%s)",
                     challenge_subtype, tile_count, canvas_count, is_logic_puzzle)

            # Skip drag-drop challenges - refresh to get image grid
            if challenge_subtype == "drag_drop":
                log.info("[hCaptcha] Drag-drop challenge - refreshing for image grid...")
                try:
                    await challenge_frame.evaluate(_CLICK_REFRESH_JS)
                    await asyncio.sleep(3)
                    continue
                except Exception as e:
                    log.warning("[hCaptcha] Refresh failed: %s", e)
                    return None

            # ── Screenshot ──
            screenshot_bytes = await self._screenshot_challenge(page, challenge_frame)

            # ── Get tiles from vision model ──
            answer = []
            if screenshot_bytes and self._classifier is not None:
                b64_image = base64.b64encode(screenshot_bytes).decode()
                
                # Enhance question with challenge type context
                enhanced_question = question
                if challenge_subtype == "logic_puzzle":
                    enhanced_question = (
                        f"[LOGIC PUZZLE - {tile_count} cells] {question}\n"
                        f"This is a logic puzzle with {tile_count} options. "
                        f"Select the SINGLE correct answer."
                    )
                elif tile_count <= 6:
                    enhanced_question = (
                        f"[SMALL GRID - {tile_count} cells] {question}\n"
                        f"Grid has {tile_count} cells numbered 0-{tile_count-1}."
                    )
                else:
                    enhanced_question = (
                        f"[IMAGE GRID - {tile_count} cells] {question}\n"
                        f"Grid has {tile_count} cells numbered 0-{tile_count-1}. "
                        f"Select ALL matching cells."
                    )
                
                log.info("[hCaptcha] Calling vision model with enhanced prompt...")
                log.info("[hCaptcha] Enhanced question: %s", enhanced_question[:150])
                try:
                    result = await self._classifier.solve({
                        "type": "HCaptchaClassification",
                        "question": enhanced_question,
                        "image": b64_image,
                    })
                    log.info("[hCaptcha] Vision raw result: %s", result)
                    answer = result.get("answer", [])
                    if not isinstance(answer, list):
                        # Handle boolean answer (single-cell logic puzzles)
                        if isinstance(answer, bool):
                            answer = [0] if answer else [1]
                        else:
                            answer = []
                    log.info("[hCaptcha] Vision answer: %s", answer)
                except Exception as e:
                    log.error("[hCaptcha] Vision model FAILED: %s", e)
                    answer = []
            else:
                log.info("[hCaptcha] No vision - using random tiles")

            # Fallback: random tiles if vision failed
            if not answer:
                tile_count = tile_info.get("count", 9)
                
                # Determine how many tiles to click based on challenge type
                if challenge_subtype == "logic_puzzle":
                    # Logic puzzles usually need exactly 1 answer
                    num_to_click = 1
                elif tile_count <= 3:
                    num_to_click = 1
                elif tile_count <= 6:
                    num_to_click = min(random.randint(1, 3), tile_count)
                else:
                    num_to_click = min(random.randint(2, 4), tile_count)
                
                answer = random.sample(range(tile_count), num_to_click)
                log.warning("[hCaptcha] Random fallback (type=%s, tiles=%d): clicking %s",
                           challenge_subtype, tile_count, answer)

            # ── Click tiles ──
            log.info("[hCaptcha] Clicking tiles %s...", answer)
            try:
                click_result = await challenge_frame.evaluate(_CLICK_TILES_JS, answer)
                log.info("[hCaptcha] Click result: %s", click_result)
            except Exception as e:
                log.error("[hCaptcha] Tile click failed: %s", e)

            await asyncio.sleep(1)

            # ── Click verify ──
            log.info("[hCaptcha] Clicking verify...")
            try:
                verify_result = await challenge_frame.evaluate(_CLICK_VERIFY_JS)
                log.info("[hCaptcha] Verify result: %s", verify_result)
            except Exception as e:
                log.error("[hCaptcha] Verify click failed: %s", e)

            # ── Wait and check result ──
            await asyncio.sleep(3)

            # Check if token was issued
            token = await page.evaluate(_EXTRACT_TOKEN_JS)
            if isinstance(token, str) and len(token) > 20:
                log.info("[hCaptcha] Token obtained after challenge %d!", challenge_attempt + 1)
                return token

            # Check if challenge still showing (need to click more or refresh)
            try:
                status = await challenge_frame.evaluate(_CHECK_CHALLENGE_STATUS_JS)
                log.info("[hCaptcha] Status after verify: %s", status)

                if status.get("hasPrompt") and not status.get("hasError"):
                    # Same challenge still showing - try clicking 2 more tiles
                    log.info("[hCaptcha] Challenge still active, adding 2 more tiles...")
                    extra = random.sample(range(tile_info.get("count", 9)), min(2, tile_info.get("count", 9)))
                    try:
                        await challenge_frame.evaluate(_CLICK_TILES_JS, extra)
                        await asyncio.sleep(0.5)
                        await challenge_frame.evaluate(_CLICK_VERIFY_JS)
                        await asyncio.sleep(3)
                        token = await page.evaluate(_EXTRACT_TOKEN_JS)
                        if isinstance(token, str) and len(token) > 20:
                            log.info("[hCaptcha] Token obtained after extra tiles!")
                            return token
                    except Exception as e:
                        log.debug("[hCaptcha] Extra click failed: %s", e)

                # If still no token, refresh for a new challenge (unless last attempt)
                if challenge_attempt < 2:
                    log.info("[hCaptcha] Refreshing for new challenge...")
                    try:
                        await challenge_frame.evaluate(_CLICK_REFRESH_JS)
                        await asyncio.sleep(3)
                        continue
                    except Exception as e:
                        log.warning("[hCaptcha] Refresh failed: %s", e)
                        break
            except Exception as e:
                log.debug("[hCaptcha] Status check error: %s", e)

        log.warning("[hCaptcha] All challenge attempts exhausted")
        return None

    async def _screenshot_challenge(self, page, challenge_frame) -> bytes | None:
        """Screenshot just the challenge iframe for clearest vision results."""
        try:
            # Find the iframe element in the parent page
            challenge_iframe_element = None
            for f in page.frames:
                if f.url and "hcaptcha.com" in f.url and ("challenge" in f.url or "checkcaptcha" in f.url):
                    iframe_handle = await page.query_selector('iframe[src*="hcaptcha.com"][src*="challenge"]')
                    if iframe_handle:
                        challenge_iframe_element = iframe_handle
                        break

            if challenge_iframe_element:
                try:
                    bbox = await challenge_iframe_element.bounding_box()
                    if bbox:
                        padding = 20
                        clip = {
                            "x": max(0, bbox["x"] - padding),
                            "y": max(0, bbox["y"] - padding),
                            "width": bbox["width"] + padding * 2,
                            "height": bbox["height"] + padding * 2,
                        }
                        screenshot = await page.screenshot(clip=clip)
                        log.info("[hCaptcha] Challenge clip screenshot: %d bytes", len(screenshot))
                        return screenshot
                except Exception as e:
                    log.warning("[hCaptcha] Clip screenshot failed: %s", e)

            # Fallback: screenshot challenge frame content
            try:
                screenshot = await challenge_frame.page.screenshot()
                log.info("[hCaptcha] Full page screenshot: %d bytes", len(screenshot))
                return screenshot
            except Exception as e:
                log.error("[hCaptcha] Screenshot failed: %s", e)
        except Exception as e:
            log.error("[hCaptcha] Screenshot error: %s", e)
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
