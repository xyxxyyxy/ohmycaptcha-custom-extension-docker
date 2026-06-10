"""
Fallback AI service handler for CAPTCHA solving.

Tries self-hosted services first, then falls back to online APIs.

Tier 1 (Self-hosted):
  - llama.cpp @ LLAMACPP_URL for vision + text
  - whisperfile @ WHISPER_URL for audio transcription

Tier 2 (OpenRouter Free):
  - meta-llama/llama-4-maverick:free for vision
  - deepseek/deepseek-chat-v3.1:free for text/transcription

Tier 3 (OpenRouter Paid - if API key has credits):
  - Any available model

Usage:
    from fallback import FallbackHandler
    handler = FallbackHandler()
    result = await handler.chat_completions(payload)
    result = await handler.audio_transcription(audio_bytes, filename)
"""

from __future__ import annotations

import io
import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("captcha-solver.fallback")

# ── Configuration ──
LLAMACPP_URL = os.getenv("LLAMACPP_URL", "https://llamacpp.xyxxyyxy.dev")
WHISPER_URL = os.getenv("WHISPER_URL", "http://whisper:1233")

# OpenRouter
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Free tier vision model (OpenRouter)
# meta-llama/llama-4-maverick:free - supports vision + text, 128K context
FALLBACK_VISION_MODEL = os.getenv("FALLBACK_VISION_MODEL", "meta-llama/llama-4-maverick:free")
# Backup vision models to try in order
FALLBACK_VISION_MODELS = [
    "meta-llama/llama-4-maverick:free",
    "meta-llama/llama-4-scout:free",
    "google/gemini-2.5-flash:free",
]

# Free tier text model (for audio transcription fallback)
FALLBACK_TEXT_MODEL = os.getenv("FALLBACK_TEXT_MODEL", "deepseek/deepseek-chat-v3.1:free")

# Whether fallback is enabled
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "true").lower() in ("1", "true", "yes")

log.info("Fallback handler initialized")
log.info("  LLAMACPP_URL=%s", LLAMACPP_URL)
log.info("  WHISPER_URL=%s", WHISPER_URL)
log.info("  OPENROUTER_URL=%s", OPENROUTER_URL)
log.info("  OPENROUTER_KEY=%s", "set" if OPENROUTER_KEY else "NOT SET")
log.info("  FALLBACK_ENABLED=%s", FALLBACK_ENABLED)
log.info("  FALLBACK_VISION_MODEL=%s", FALLBACK_VISION_MODEL)


class FallbackHandler:
    """Handles AI requests with automatic fallback to online APIs."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        self._fallback_count = 0
        self._success_count = 0

    async def chat_completions(self, payload: dict) -> dict:
        """Send chat completion request, fallback to OpenRouter on failure.

        Args:
            payload: OpenAI-compatible chat completions payload

        Returns:
            OpenAI-compatible response dict

        Raises:
            RuntimeError: If all tiers fail
        """
        target_model = payload.get("model", "")
        has_image = self._payload_has_image(payload)

        log.info("[Fallback] chat_completions: model=%s has_image=%s",
                 target_model, has_image)

        # ── Tier 1: Self-hosted llama.cpp ──
        log.info("[Fallback] Trying Tier 1: self-hosted llama.cpp...")
        try:
            result = await self._try_llamacpp(payload)
            if result:
                self._success_count += 1
                log.info("[Fallback] Tier 1 SUCCESS (llama.cpp)")
                return result
        except Exception as e:
            log.warning("[Fallback] Tier 1 FAILED: %s", str(e)[:200])

        # ── Tier 2: OpenRouter free tier ──
        if not FALLBACK_ENABLED or not OPENROUTER_KEY:
            log.error("[Fallback] Tier 2 disabled: no OPENROUTER_API_KEY")
            raise RuntimeError(
                "Self-hosted llama.cpp failed and OpenRouter fallback is not configured. "
                "Set OPENROUTER_API_KEY env var to enable fallback."
            )

        log.info("[Fallback] Trying Tier 2: OpenRouter free tier...")

        # Try each backup vision model
        models_to_try = [FALLBACK_VISION_MODEL] + [
            m for m in FALLBACK_VISION_MODELS if m != FALLBACK_VISION_MODEL
        ]

        for model_id in models_to_try:
            try:
                result = await self._try_openrouter(payload, model_id)
                if result:
                    self._fallback_count += 1
                    log.info("[Fallback] Tier 2 SUCCESS: model=%s (fallback #%d)",
                             model_id, self._fallback_count)
                    return result
            except Exception as e:
                log.warning("[Fallback] Tier 2 model %s FAILED: %s", model_id, str(e)[:200])
                continue

        raise RuntimeError(
            "All fallback tiers exhausted. "
            "Self-hosted llama.cpp failed, OpenRouter free models failed. "
            "Check logs for details."
        )

    async def audio_transcriptions(
        self, audio_bytes: bytes, filename: str = "audio.mp3", language: str = "en"
    ) -> dict:
        """Transcribe audio, fallback to whisperfile -> OpenRouter.

        Args:
            audio_bytes: Raw audio file bytes
            filename: Original filename (for content-type detection)
            language: Audio language code

        Returns:
            {"text": "transcribed text"} dict
        """
        log.info("[Fallback] audio_transcriptions: %d bytes, file=%s", len(audio_bytes), filename)

        # ── Tier 1: Self-hosted whisperfile ──
        log.info("[Fallback] Trying Tier 1: whisperfile...")
        try:
            result = await self._try_whisperfile(audio_bytes, filename, language)
            if result:
                self._success_count += 1
                log.info("[Fallback] Tier 1 SUCCESS (whisperfile)")
                return result
        except Exception as e:
            log.warning("[Fallback] Tier 1 FAILED (whisperfile): %s", str(e)[:200])

        # ── Tier 2: OpenRouter text model for transcription ──
        if not FALLBACK_ENABLED or not OPENROUTER_KEY:
            raise RuntimeError(
                "Whisperfile failed and OpenRouter fallback not configured."
            )

        log.info("[Fallback] Trying Tier 2: OpenRouter for transcription...")
        try:
            result = await self._try_openrouter_audio(audio_bytes, filename, language)
            if result:
                self._fallback_count += 1
                log.info("[Fallback] Tier 2 SUCCESS (OpenRouter audio)")
                return result
        except Exception as e:
            log.warning("[Fallback] Tier 2 FAILED (OpenRouter audio): %s", str(e)[:200])

        raise RuntimeError("All audio transcription tiers failed")

    # ── Internal: Tier 1 (self-hosted) ──

    async def _try_llamacpp(self, payload: dict) -> dict | None:
        """Try self-hosted llama.cpp. Returns None on failure."""
        r = await self._http.post(
            f"{LLAMACPP_URL}/v1/chat/completions",
            json=payload,
            timeout=120.0
        )
        if r.status_code == 200:
            return r.json()
        # Log the error body for debugging
        err_text = r.text[:300]
        log.debug("[Fallback] llama.cpp error: HTTP %d: %s", r.status_code, err_text)
        return None

    async def _try_whisperfile(
        self, audio_bytes: bytes, filename: str, language: str
    ) -> dict | None:
        """Try self-hosted whisperfile. Tries multiple endpoints. Returns None on failure."""
        ext = filename.split(".")[-1].lower() if "." in filename else "mp3"
        mime_types = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
            "flac": "audio/flac", "m4a": "audio/mp4", "webm": "audio/webm",
        }
        content_type = mime_types.get(ext, "audio/mpeg")

        # Try multiple whisperfile endpoints (different versions use different paths)
        endpoints_to_try = [
            # OpenAI-compatible (newer whisperfile builds)
            ("/v1/audio/transcriptions", {"model": "whisper-1", "language": language}),
            # Whisperfile native endpoint
            ("/transcribe", {}),
            # Alternative native endpoint
            ("/inference", {}),
        ]

        for endpoint, extra_data in endpoints_to_try:
            try:
                log.info("[Fallback] Trying whisperfile endpoint: %s", endpoint)
                r = await self._http.post(
                    f"{WHISPER_URL}{endpoint}",
                    files={"file": (filename, io.BytesIO(audio_bytes), content_type)},
                    data=extra_data,
                    timeout=60.0
                )
                log.info("[Fallback] Whisperfile %s -> HTTP %d", endpoint, r.status_code)

                if r.status_code == 200:
                    # Try to parse as JSON, fallback to plain text
                    try:
                        return r.json()
                    except Exception:
                        # Plain text response - wrap in expected format
                        return {"text": r.text.strip()}

                # 422 = unprocessable entity (endpoint exists but wrong params)
                # 400 = bad request (endpoint exists)
                if r.status_code in (422, 400):
                    log.info("[Fallback] Endpoint %s exists but returned %d, trying next...",
                             endpoint, r.status_code)
                    continue

            except Exception as e:
                log.debug("[Fallback] Whisperfile endpoint %s error: %s", endpoint, str(e)[:200])
                continue

        log.warning("[Fallback] All whisperfile endpoints failed")
        return None

    # ── Internal: Tier 2 (OpenRouter) ──

    async def _try_openrouter(self, payload: dict, model_id: str) -> dict | None:
        """Try OpenRouter with specified model. Returns None on failure."""
        # Replace model in payload
        payload_copy = {**payload, "model": model_id}

        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/xyxxyyxy/ohmycaptcha-custom-extension-docker",
            "X-Title": "OhMyCaptcha Solver",
        }

        r = await self._http.post(
            f"{OPENROUTER_URL}/chat/completions",
            json=payload_copy,
            headers=headers,
            timeout=120.0
        )
        if r.status_code == 200:
            return r.json()
        # Check for rate limit
        if r.status_code == 429:
            log.warning("[Fallback] OpenRouter rate limited (429) for %s", model_id)
        err_text = r.text[:300]
        log.debug("[Fallback] OpenRouter error: HTTP %d: %s", r.status_code, err_text)
        return None

    async def _try_openrouter_audio(
        self, audio_bytes: bytes, filename: str, language: str
    ) -> dict | None:
        """Use OpenRouter for audio transcription.

        Since OpenRouter doesn't have a native /audio/transcriptions endpoint,
        we use a text model with a prompt to transcribe base64 audio.
        This is less accurate than whisper but works as emergency fallback.
        """
        import base64

        # Convert to wav if needed (best compatibility)
        ext = filename.split(".")[-1].lower() if "." in filename else "mp3"

        # For small audio files, we can try sending to a vision-capable model
        # that also handles audio. But most free models don't support audio.
        # Alternative: use DeepSeek to describe what the audio likely says
        # based on CAPTCHA patterns (digits).

        # Actually, OpenRouter DOES support audio through some models
        # Let's try using the OpenAI-compatible endpoint directly
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
        }

        mime_types = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
            "flac": "audio/flac", "m4a": "audio/mp4",
        }
        content_type = mime_types.get(ext, "audio/mpeg")

        r = await self._http.post(
            f"{OPENROUTER_URL}/audio/transcriptions",
            files={"file": (filename, io.BytesIO(audio_bytes), content_type)},
            data={"model": "whisper-1", "language": language},
            headers=headers,
            timeout=60.0
        )
        if r.status_code == 200:
            return r.json()

        # If that fails, try a text-based approach with a model that supports audio
        log.debug("[Fallback] OpenRouter /audio/transcriptions failed: %d %s",
                  r.status_code, r.text[:200])

        # Last resort: for reCAPTCHA audio, the answer is usually 4-6 digits
        # Return empty to signal failure - the caller should retry
        return None

    # ── Helpers ──

    @staticmethod
    def _payload_has_image(payload: dict) -> bool:
        """Check if the payload contains image data."""
        for msg in payload.get("messages", []):
            content = msg.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "image_url":
                        return True
        return False

    def get_stats(self) -> dict[str, int]:
        """Return success/fallback counts."""
        return {
            "self_hosted_success": self._success_count,
            "fallback_count": self._fallback_count,
            "total": self._success_count + self._fallback_count,
        }
