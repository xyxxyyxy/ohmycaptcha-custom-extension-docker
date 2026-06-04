"""reCAPTCHA v2 solver using Playwright browser automation.

Supports NoCaptchaTaskProxyless, RecaptchaV2TaskProxyless,
and RecaptchaV2EnterpriseTaskProxyless task types.

Strategy:
  1. Visit the target page with a realistic browser context.
  2. Simulate human-like mouse movement before clicking.
  3. Click the reCAPTCHA checkbox.
  4. If challenge appears, check for "Try again later" bot detection.
  5. Switch to audio challenge, download audio via #audio-source,
     transcribe via whisperfile, submit answer.
  6. Retry loop handles "Multiple correct solutions required".
  7. Extract the gRecaptchaResponse token.

Anti-detection measures (June 2026):
- Human-like mouse movement (Bezier curves) before every click
- Random delays between actions
- #audio-source element extraction (used by GoogleRecaptchaBypass)
- Bot detection check for "Try again later" / automated queries
- Multiple retry attempts for audio challenge
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any

import httpx
from playwright.async_api import Browser, Playwright, async_playwright

from ..core.config import Config

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

from .stealth import STEALTH_JS, WAIT_UNTIL

log = logging.getLogger(__name__)

_EXTRACT_TOKEN_JS = """
() => {
    const textarea = document.querySelector('#g-recaptcha-response')
        || document.querySelector('[name="g-recaptcha-response"]');
    if (textarea && textarea.value && textarea.value.length > 20) {
        return textarea.value;
    }
    const gr = window.grecaptcha?.enterprise || window.grecaptcha;
    if (gr && typeof gr.getResponse === 'function') {
        const resp = gr.getResponse();
        if (resp && resp.length > 20) return resp;
    }
    return null;
}
"""

# JS: Check for bot detection message inside the challenge iframe
_CHECK_BOT_DETECTION_JS = """
() => {
    const tryAgainEl = document.querySelector('body');
    const bodyText = tryAgainEl ? tryAgainEl.innerText : '';
    const isBlocked = bodyText.includes('Try again later')
        || bodyText.includes('automated queries')
        || bodyText.includes('sending automated')
        || bodyText.includes('computer or network may be sending')
        || bodyText.includes('unusual traffic')
        || bodyText.includes('suspected of being a bot');
    return {
        blocked: isBlocked,
        bodyText: bodyText.substring(0, 200)
    };
}
"""

# JS: Extract audio source URL from the challenge iframe
_GET_AUDIO_URL_JS = """
() => {
    // Primary: #audio-source is the standard element (confirmed by GoogleRecaptchaBypass)
    const audioSource = document.querySelector('#audio-source');
    if (audioSource) {
        const src = audioSource.getAttribute('src');
        if (src) return {url: src, method: 'audio-source'};
    }
    // Fallback: audio element
    const audio = document.querySelector('audio');
    if (audio) {
        const src = audio.getAttribute('src') || audio.querySelector('source')?.getAttribute('src');
        if (src) return {url: src, method: 'audio-element'};
    }
    // Fallback: download link
    const link = document.querySelector('.rc-audiochallenge-tdownload-link, a[href*=".mp3"], a[href*=".wav"]');
    if (link) {
        const href = link.getAttribute('href');
        if (href) return {url: href, method: 'download-link'};
    }
    // Last resort: any element with .mp3 or .wav src
    const allSources = document.querySelectorAll('[src*=".mp3"], [src*=".wav"], [src*=".ogg"]');
    for (const el of allSources) {
        const src = el.getAttribute('src');
        if (src) return {url: src, method: 'any-source'};
    }
    return {url: null, method: 'none', html: document.body.innerHTML.substring(0, 500)};
}
"""

# JS: Check if checkbox is already solved
_IS_CHECKBOX_SOLVED_JS = """
() => {
    const checked = document.querySelector('.recaptcha-checkbox-checked');
    const checkmark = document.querySelector('.recaptcha-checkbox-checkmark');
    return !!(checked || (checkmark && checkmark.style.display !== 'none'));
}
"""

# JS: Check for "Multiple correct solutions required" error
_CHECK_MULTIPLE_CORRECT_JS = """
() => {
    const errorEl = document.querySelector('.rc-audiochallenge-error-message');
    if (errorEl && errorEl.textContent.toLowerCase().includes('multiple correct')) {
        return {multipleCorrect: true, text: errorEl.textContent.trim()};
    }
    return {multipleCorrect: false, text: ''};
}
"""

# JS: Click reload button to get new audio challenge
_CLICK_RELOAD_JS = """
() => {
    const btn = document.querySelector('#recaptcha-reload-button');
    if (btn) { btn.click(); return true; }
    return false;
}
"""


class RecaptchaV2Solver:
    """Solves reCAPTCHA v2 tasks via Playwright with CDP-connected Brave.

    Uses audio challenge path with anti-detection measures:
    - Human-like mouse movement before clicks
    - #audio-source element for reliable audio URL extraction
    - Bot detection check for "automated queries" message
    - Retry loop for "Multiple correct solutions required"
    """

    def __init__(self, config: Config, browser: Browser | None = None) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = browser
        self._owns_browser = browser is None

    async def start(self) -> None:
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await _connect_cdp(self._playwright)
        log.info("RecaptchaV2Solver browser started")

    async def stop(self) -> None:
        if self._owns_browser:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        log.info("RecaptchaV2Solver stopped")

    async def solve(self, params: dict[str, Any]) -> dict[str, Any]:
        website_url = params["websiteURL"]
        website_key = params["websiteKey"]
        is_invisible = params.get("isInvisible", False)

        last_error: Exception | None = None
        for attempt in range(self._config.captcha_retries):
            try:
                token = await self._solve_once(website_url, website_key, is_invisible)
                return {"gRecaptchaResponse": token}
            except Exception as exc:
                last_error = exc
                log.warning(
                    "reCAPTCHA v2 attempt %d/%d failed: %s",
                    attempt + 1,
                    self._config.captcha_retries,
                    exc,
                )
                if attempt < self._config.captcha_retries - 1:
                    await asyncio.sleep(2)

        raise RuntimeError(
            f"reCAPTCHA v2 failed after {self._config.captcha_retries} attempts: {last_error}"
        )

    async def _get_page(self):
        """Get a page from the default browser context where extensions run.

        browser.new_page() creates a NEW isolated context (like incognito)
        that has no access to extensions, cookies, or profile data.
        We must use browser.contexts[0] to get the default context.

        Returns (page, should_close) tuple.
        """
        contexts = self._browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            if pages:
                log.info("[reCAPTCHA] Reusing existing page in default context (%d pages)", len(pages))
                page = pages[0]
                await page.set_viewport_size({"width": 1920, "height": 1080})
                return page, False
            log.info("[reCAPTCHA] Creating new page in default context (extensions active)")
            page = await context.new_page()
            return page, True
        else:
            log.warning("[reCAPTCHA] No default context, falling back to isolated context")
            page = await self._browser.new_page(viewport={"width": 1920, "height": 1080})
            return page, True

    async def _solve_once(
        self, website_url: str, website_key: str, is_invisible: bool
    ) -> str:
        assert self._browser is not None

        page, should_close = await self._get_page()
        await page.add_init_script(STEALTH_JS)

        try:
            timeout_ms = self._config.browser_timeout * 1000
            await page.goto(website_url, wait_until=WAIT_UNTIL, timeout=timeout_ms)

            # Human-like mouse movement after page load
            await self._human_mouse_move(page, 100, 200, 400, 350)
            await asyncio.sleep(random.uniform(0.5, 1.5))

            if is_invisible:
                token = await page.evaluate(
                    """
                    ([key]) => new Promise((resolve, reject) => {
                        const gr = window.grecaptcha?.enterprise || window.grecaptcha;
                        if (!gr) { reject(new Error('grecaptcha not found')); return; }
                        gr.ready(() => {
                            gr.execute(key).then(resolve).catch(reject);
                        });
                    })
                    """,
                    [website_key],
                )
            else:
                token = await self._solve_checkbox(page)

            if not isinstance(token, str) or len(token) < 20:
                raise RuntimeError(f"Invalid reCAPTCHA v2 token: {token!r}")

            log.info("Got reCAPTCHA v2 token (len=%d)", len(token))
            return token
        finally:
            if should_close:
                await page.close()

    async def _solve_checkbox(self, page: Any) -> str | None:
        """Click the reCAPTCHA checkbox. If challenge appears, try audio path."""
        # The checkbox iframe always has title="reCAPTCHA"
        checkbox_frame = page.frame_locator('iframe[title="reCAPTCHA"]').first
        checkbox = checkbox_frame.locator("#recaptcha-anchor")

        # Move mouse to checkbox area before clicking
        await self._human_mouse_move(page, 400, 350, 520, 420)
        await checkbox.click(timeout=10_000)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Check if token was issued immediately (low-risk sessions)
        token = await page.evaluate(_EXTRACT_TOKEN_JS)
        if isinstance(token, str) and len(token) > 20:
            return token

        # Check if checkbox is already checked (solved without token visible yet)
        try:
            checkbox_inner = page.frame_locator('iframe[title="reCAPTCHA"]').first
            is_checked = await checkbox_inner.evaluate(_IS_CHECKBOX_SOLVED_JS)
            if is_checked:
                log.info("Checkbox appears checked, waiting for token...")
                for _ in range(4):
                    await asyncio.sleep(2)
                    token = await page.evaluate(_EXTRACT_TOKEN_JS)
                    if isinstance(token, str) and len(token) > 20:
                        return token
        except Exception as e:
            log.debug("Checkbox solved check failed: %s", e)

        # Challenge dialog appeared — try audio challenge path
        log.info("reCAPTCHA challenge detected, attempting audio path")
        try:
            token = await self._solve_audio_challenge(page)
        except Exception as exc:
            log.warning("Audio challenge path failed: %s", exc)
            token = None

        return token

    async def _solve_audio_challenge(self, page: Any) -> str | None:
        """Click audio button, download audio, transcribe, submit. With retry loop."""
        # The challenge bframe has title containing "recaptcha challenge"
        bframe = page.frame_locator('iframe[title*="recaptcha challenge"]')

        # Human-like mouse movement to audio button
        await self._human_mouse_move(page, 600, 400, 650, 500)

        # Click the audio challenge button (headphones icon)
        audio_btn = bframe.locator("#recaptcha-audio-button")
        await audio_btn.click(timeout=8_000)
        log.info("Clicked audio challenge button, waiting for audio to load...")
        await asyncio.sleep(random.uniform(2.5, 4.0))

        # Click the PLAY button to start audio playback (audio doesn't auto-play)
        try:
            play_btn = bframe.locator(".rc-button-default, #recaptcha-audio-play-button, .rc-audiochallenge-play-button")
            await play_btn.click(timeout=5_000)
            log.info("Clicked audio play button")
            await asyncio.sleep(1.5)
        except Exception:
            log.debug("No play button found or audio auto-played")

        # Get the inner frame for JS evaluation
        # reCAPTCHA challenge iframe URL contains "bframe" not "challenge"
        challenge_frame = None
        all_frame_urls = []
        for f in page.frames:
            url = f.url or ""
            all_frame_urls.append(url[:120])
            if f.url and "recaptcha" in f.url and ("challenge" in f.url or "bframe" in f.url):
                challenge_frame = f
                log.info("Found challenge frame: %s", url[:120])
                break

        if not challenge_frame:
            log.warning("All frame URLs: %s", all_frame_urls)

        # Check for bot detection message
        if challenge_frame:
            try:
                detection = await challenge_frame.evaluate(_CHECK_BOT_DETECTION_JS)
                log.info("Bot detection check: blocked=%s", detection.get("blocked"))
                if detection.get("blocked"):
                    log.error("reCAPTCHA bot detection triggered: %s", detection.get("bodyText", ""))
                    # Wait and retry once
                    log.info("Waiting 10s before retry due to bot detection...")
                    await asyncio.sleep(10)
                    # Try clicking reload to get a fresh challenge
                    try:
                        await challenge_frame.evaluate(_CLICK_RELOAD_JS)
                        await asyncio.sleep(3)
                        # Re-check
                        detection = await challenge_frame.evaluate(_CHECK_BOT_DETECTION_JS)
                        if detection.get("blocked"):
                            raise RuntimeError(
                                f"reCAPTCHA bot detection persists after reload: {detection.get('bodyText', '')}"
                            )
                    except Exception as reload_err:
                        raise RuntimeError(
                            f"reCAPTCHA bot detection: {detection.get('bodyText', '')}. "
                            f"Reload failed: {reload_err}"
                        )
            except Exception as e:
                if "bot detection" in str(e).lower():
                    raise
                log.debug("Bot detection check error (non-fatal): %s", e)

        # Retry loop for audio challenge (handles "Multiple correct solutions required")
        max_attempts = 5
        for attempt in range(max_attempts):
            log.info("Audio challenge attempt %d/%d", attempt + 1, max_attempts)

            # Re-get challenge frame (it may reload)
            # reCAPTCHA challenge iframe URL: .../bframe?k=... (contains "bframe" not "challenge")
            challenge_frame = None
            for f in page.frames:
                if f.url and "recaptcha" in f.url and ("challenge" in f.url or "bframe" in f.url):
                    challenge_frame = f
                    break

            if not challenge_frame:
                log.warning("Challenge frame not found (checked for 'challenge' or 'bframe' in recaptcha URLs)")
                # Check if token appeared (challenge solved without audio)
                token = await page.evaluate(_EXTRACT_TOKEN_JS)
                if isinstance(token, str) and len(token) > 20:
                    log.info("Token found despite no challenge frame")
                    return token
                break

            # Get the audio source URL via JS inside the iframe
            audio_src = None
            method = "none"
            try:
                result = await challenge_frame.evaluate(_GET_AUDIO_URL_JS)
                audio_src = result.get("url")
                method = result.get("method", "none")
                log.info("Audio URL method: %s, url: %s", method,
                         audio_src[:80] + "..." if audio_src and len(audio_src) > 80 else audio_src)
                if not audio_src:
                    log.warning("Audio HTML snippet: %s", result.get("html", "N/A"))
            except Exception as e:
                log.error("Audio URL JS extraction failed: %s", e)

            # Fallback: try Playwright locators
            if not audio_src:
                log.info("Trying Playwright locator fallback for audio URL...")
                bframe = page.frame_locator('iframe[title*="recaptcha challenge"]')
                for selector in ["#audio-source", "audio", "audio source", ".rc-audiochallenge-tdownload-link"]:
                    try:
                        element = bframe.locator(selector).first
                        audio_src = await element.get_attribute("src", timeout=3_000) \
                            or await element.get_attribute("href", timeout=1_000)
                        if audio_src:
                            log.info("Audio URL found via Playwright selector %s", selector)
                            break
                    except Exception:
                        continue

            if not audio_src:
                # Check if we're blocked
                try:
                    detection = await challenge_frame.evaluate(_CHECK_BOT_DETECTION_JS)
                    if detection.get("blocked"):
                        raise RuntimeError(
                            f"reCAPTCHA bot detection (no audio): {detection.get('bodyText', '')}"
                        )
                except Exception:
                    pass
                raise RuntimeError(
                    f"Could not find audio challenge download link (method={method}). "
                    "Bot detection may be active."
                )

            # Download the audio file
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    # Add browser-like headers
                    headers = {
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                        "Accept": "audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                    resp = await client.get(audio_src, headers=headers)
                    resp.raise_for_status()
                    audio_bytes = resp.content
                    log.info("Audio downloaded: %d bytes", len(audio_bytes))
            except Exception as e:
                raise RuntimeError(f"Audio download failed: {e}")

            # Transcribe via whisperfile
            transcript = await self._transcribe_audio(audio_bytes)
            log.info("Audio transcribed (attempt %d): %r", attempt + 1,
                     transcript[:50] if transcript else None)

            if not transcript:
                if attempt < max_attempts - 1:
                    log.info("Empty transcript, reloading challenge...")
                    try:
                        await challenge_frame.evaluate(_CLICK_RELOAD_JS)
                        await asyncio.sleep(3)
                    except Exception:
                        pass
                    continue
                raise RuntimeError("Audio transcription returned empty result after all attempts")

            # Submit the transcript
            bframe = page.frame_locator('iframe[title*="recaptcha challenge"]')
            audio_input = bframe.locator("#audio-response")
            await audio_input.fill(transcript.strip().lower())

            # Small delay before clicking verify
            await asyncio.sleep(random.uniform(0.5, 1.5))
            verify_btn = bframe.locator("#recaptcha-verify-button")
            await verify_btn.click(timeout=8_000)
            await asyncio.sleep(random.uniform(2.0, 3.5))

            # Check if solved
            token = await page.evaluate(_EXTRACT_TOKEN_JS)
            if isinstance(token, str) and len(token) > 20:
                log.info("Audio challenge solved on attempt %d", attempt + 1)
                return token

            # Check for "Multiple correct solutions required" error
            try:
                if challenge_frame:
                    multi_check = await challenge_frame.evaluate(_CHECK_MULTIPLE_CORRECT_JS)
                    if multi_check.get("multipleCorrect"):
                        log.info("Multiple correct solutions required, continuing...")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(2)
                            continue
            except Exception:
                pass

            # Check if checkbox is now checked
            try:
                checkbox_inner = page.frame_locator('iframe[title="reCAPTCHA"]').first
                is_checked = await checkbox_inner.evaluate(_IS_CHECKBOX_SOLVED_JS)
                if is_checked:
                    log.info("Checkbox is checked after audio submission")
                    for _ in range(3):
                        await asyncio.sleep(2)
                        token = await page.evaluate(_EXTRACT_TOKEN_JS)
                        if isinstance(token, str) and len(token) > 20:
                            return token
            except Exception:
                pass

            # If not solved and not multiple-correct, try reloading
            if attempt < max_attempts - 1:
                try:
                    if challenge_frame:
                        await challenge_frame.evaluate(_CLICK_RELOAD_JS)
                        await asyncio.sleep(3)
                except Exception:
                    pass

        # All attempts exhausted
        token = await page.evaluate(_EXTRACT_TOKEN_JS)
        if isinstance(token, str) and len(token) > 20:
            return token
        return None

    async def _transcribe_audio(self, audio_bytes: bytes) -> str | None:
        """Send audio bytes to the whisperfile transcription endpoint."""
        from io import BytesIO

        # Determine audio extension from magic bytes
        ext = "mp3"
        if audio_bytes[:4] == b"RIFF":
            ext = "wav"
        elif audio_bytes[:4] == b"OggS":
            ext = "ogg"
        elif audio_bytes[:4] == b"fLaC":
            ext = "flac"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._config.captcha_base_url}/audio/transcriptions",
                files={"file": (f"audio.{ext}", BytesIO(audio_bytes), f"audio/{ext}")},
                data={"model": "whisper-1", "language": "en"},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Transcription API error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            text = data.get("text", "")
            # Whisper often returns digits as words; normalize
            text = text.strip().lower()
            word_to_digit = {
                "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
            }
            for word, digit in word_to_digit.items():
                text = text.replace(word, digit)
            return text

    async def _human_mouse_move(self, page, x1: int, y1: int, x2: int, y2: int) -> None:
        """Simulate human-like mouse movement between two points using Bezier curves."""
        steps = random.randint(8, 15)
        # Control point for quadratic Bezier (adds curve + randomness)
        cx = (x1 + x2) / 2 + random.randint(-80, 80)
        cy = (y1 + y2) / 2 + random.randint(-50, 50)
        for i in range(steps):
            t = (i + 1) / steps
            # Quadratic Bezier curve
            bx = (1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2
            by = (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2
            # Add slight jitter
            bx += random.randint(-3, 3)
            by += random.randint(-3, 3)
            await page.mouse.move(int(bx), int(by))
            # Variable speed (slower at start/end, faster in middle)
            delay = 0.03 + random.uniform(0, 0.05) if i < 3 or i > steps - 3 else 0.01 + random.uniform(0, 0.02)
            await asyncio.sleep(delay)
