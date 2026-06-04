#!/usr/bin/env python3
"""
Comprehensive service test for the full CAPTCHA solving stack.

Tests every component and saves results to a timestamped log file.
Run with: python3 test-all-services.py

Requires: pip install httpx Pillow
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image

# ── Configuration ──
LLAMACPP_URL = os.getenv("LLAMACPP_URL", "https://llamacpp.xyxxyyxy.dev")
SHIM_URL = os.getenv("SHIM_URL", "http://localhost:1232")
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:1231")
WHISPER_URL = os.getenv("WHISPER_URL", "http://localhost:1233")
CDP_URL = os.getenv("CDP_URL", "http://localhost:9222")
VISION_MODEL = os.getenv("VISION_MODEL", "Qwen3VL-8B-Instruct-Q8_0")

RESULTS: list[dict] = []
http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)


def log(category: str, message: str, status: str = "info"):
    """Log to console and save for report."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] [{status.upper():7}] [{category:20}] {message}"
    print(line)
    RESULTS.append({"time": timestamp, "category": category, "status": status, "message": message})


def section(name: str):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")


async def test_llamacpp_health():
    section("1. llama.cpp Direct - Health")
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/health")
        log("llama-health", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "warn")
        if r.status_code == 200:
            log("llama-health", f"Response: {r.text[:200]}", "info")
    except Exception as e:
        log("llama-health", f"FAILED: {e}", "fail")


async def test_llamacpp_models():
    section("2. llama.cpp Direct - /models")
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/models")
        log("llama-models", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            models = data.get("data", [])
            log("llama-models", f"Models returned: {len(models)}", "info")
            for i, m in enumerate(models):
                if isinstance(m, dict):
                    mid = m.get("id", "unknown")
                    log("llama-models", f"  Model {i}: {mid}", "info")
                    # Check for vision-related fields
                    if "mmproj" in str(m).lower():
                        log("llama-models", f"  -> Has mmproj field (vision enabled!)", "pass")
                else:
                    log("llama-models", f"  Model {i}: {m}", "info")
            # Check if target model is loaded
            all_ids = [m.get("id", "") if isinstance(m, dict) else str(m) for m in models]
            target_loaded = any(VISION_MODEL.lower() in id.lower() for id in all_ids)
            log("llama-models", f"Target '{VISION_MODEL}' loaded: {target_loaded}", "pass" if target_loaded else "warn")
    except Exception as e:
        log("llama-models", f"FAILED: {e}", "fail")


async def test_llamacpp_text_chat():
    section("3. llama.cpp Direct - Text Chat")
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": "What is 2+2? Answer with just the number."}],
        "temperature": 0.1,
        "max_tokens": 10
    }
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        log("llama-text", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            log("llama-text", f"Answer: '{answer}'", "pass")
        else:
            log("llama-text", f"Error: {r.text[:300]}", "fail")
    except Exception as e:
        log("llama-text", f"FAILED: {e}", "fail")


async def test_llamacpp_vision_chat():
    section("4. llama.cpp Direct - Vision Chat (CRITICAL)")
    # Create tiny test image
    img = Image.new("RGB", (50, 50), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    log("llama-vision", f"Test image: {len(b64)} bytes base64", "info")

    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What color is this? One word."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        "temperature": 0.1,
        "max_tokens": 10
    }
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        log("llama-vision", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            log("llama-vision", f"Answer: '{answer}'", "pass")
            log("llama-vision", "VISION IS WORKING!", "pass")
        else:
            err = r.text[:500]
            log("llama-vision", f"Error body: {err}", "fail")
            if "vision" in err.lower() or "mmproj" in err.lower():
                log("llama-vision", "-> Need --mmproj flag on llama-server", "warn")
            elif "proxy" in err.lower():
                log("llama-vision", "-> Proxy can't reach backend. Check nginx routing.", "warn")
    except Exception as e:
        log("llama-vision", f"FAILED: {e}", "fail")


async def test_shim_health():
    section("5. Captcha-Solver Shim - Health")
    try:
        r = await http_client.get(f"{SHIM_URL}/health")
        log("shim-health", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            log("shim-health", f"shim_status: {data.get('shim_status')}", "info")
            log("shim-health", f"llamacpp_status: {data.get('llamacpp_status')}", "info")
            log("shim-health", f"currently_loaded: {data.get('currently_loaded')}", "info")
            log("shim-health", f"vision_model_target: {data.get('vision_model_target')}", "info")
    except Exception as e:
        log("shim-health", f"FAILED: {e}", "fail")


async def test_shim_models():
    section("6. Captcha-Solver Shim - /v1/models")
    try:
        r = await http_client.get(f"{SHIM_URL}/v1/models")
        log("shim-models", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            models = data.get("data", [])
            log("shim-models", f"Models: {len(models)}", "info")
    except Exception as e:
        log("shim-models", f"FAILED: {e}", "fail")


async def test_shim_vision():
    section("7. Captcha-Solver Shim - Vision Chat")
    img = Image.new("RGB", (50, 50), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What color? One word."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        "temperature": 0.1,
        "max_tokens": 10
    }
    try:
        r = await http_client.post(f"{SHIM_URL}/v1/chat/completions", json=payload)
        log("shim-vision", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            log("shim-vision", f"Answer: '{answer}'", "pass")
        else:
            log("shim-vision", f"Error: {r.text[:300]}", "fail")
    except Exception as e:
        log("shim-vision", f"FAILED: {e}", "fail")


async def test_bridge_health():
    section("8. Captcha Bridge - Health")
    try:
        r = await http_client.get(f"{BRIDGE_URL}/api/v1/health")
        log("bridge-health", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            log("bridge-health", f"Response: {r.text[:200]}", "info")
    except Exception as e:
        log("bridge-health", f"FAILED: {e}", "fail")


async def test_whisper():
    section("9. Whisperfile - Health")
    try:
        r = await http_client.get(f"{WHISPER_URL}/health", timeout=5.0)
        log("whisper", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "warn")
    except Exception as e:
        log("whisper", f"Not reachable: {e}", "warn")
        # Try alternative endpoint
        try:
            r = await http_client.get(f"{WHISPER_URL}/v1/audio/transcriptions", timeout=5.0)
            log("whisper", f"Alt endpoint status: {r.status_code}", "info")
        except Exception as e2:
            log("whisper", f"Alt endpoint also failed: {e2}", "warn")


async def test_brave_cdp():
    section("10. Brave CDP Connectivity")
    try:
        r = await http_client.get(f"{CDP_URL}/json/version")
        log("brave-cdp", f"Status: {r.status_code}", "pass" if r.status_code == 200 else "fail")
        if r.status_code == 200:
            data = r.json()
            log("brave-cdp", f"Browser: {data.get('Browser', 'unknown')}", "info")
            log("brave-cdp", f"Version: {data.get('Browser_Version', 'unknown')}", "info")
    except Exception as e:
        log("brave-cdp", f"FAILED: {e}", "fail")
        log("brave-cdp", "-> Is Brave running with --remote-debugging-port=9222?", "warn")


async def test_hcaptcha_screenshot():
    section("11. hCaptcha Screenshot + Vision (Optional)")
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log("hcaptcha", "playwright not installed, skipping", "warn")
        return

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            contexts = browser.contexts
            if contexts and contexts[0].pages:
                page = contexts[0].pages[0]
            else:
                page = await (contexts[0].new_page() if contexts else browser.new_page())

            log("hcaptcha", "Navigating to hCaptcha demo...", "info")
            await page.goto("https://accounts.hcaptcha.com/demo")
            await asyncio.sleep(2)

            # Click checkbox
            for f in page.frames:
                if f.url and "hcaptcha.com" in f.url and ("checkbox" in f.url or "anchor" in f.url):
                    await f.evaluate("() => { const cb = document.querySelector('#checkbox'); if (cb) cb.click(); }")
                    log("hcaptcha", "Clicked checkbox", "info")
                    break

            await asyncio.sleep(3)

            # Take screenshot
            screenshot = await page.screenshot()
            log("hcaptcha", f"Screenshot: {len(screenshot)} bytes", "info")

            # Save for inspection
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/hcaptcha_screenshot_{ts}.png"
            with open(path, "wb") as f:
                f.write(screenshot)
            log("hcaptcha", f"Saved screenshot to {path}", "info")

            # Resize and test vision
            img = Image.open(io.BytesIO(screenshot))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            if max(img.size) > 512:
                img.thumbnail((512, 512))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()

            payload = {
                "model": VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What does this CAPTCHA ask? Describe briefly."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }],
                "temperature": 0.1,
                "max_tokens": 100
            }

            log("hcaptcha", f"Sending {len(b64)} bytes to vision model...", "info")
            r = await http_client.post(f"{SHIM_URL}/v1/chat/completions", json=payload)
            log("hcaptcha", f"Vision response: {r.status_code}", "pass" if r.status_code == 200 else "fail")
            if r.status_code == 200:
                answer = r.json()["choices"][0]["message"]["content"]
                log("hcaptcha", f"Description: {answer[:200]}", "pass")
            else:
                log("hcaptcha", f"Error: {r.text[:300]}", "fail")

            await browser.close()
    except Exception as e:
        log("hcaptcha", f"FAILED: {e}", "fail")


def print_summary():
    section("SUMMARY")
    passed = sum(1 for r in RESULTS if r["status"] == "pass")
    failed = sum(1 for r in RESULTS if r["status"] == "fail")
    warnings = sum(1 for r in RESULTS if r["status"] == "warn")
    total = passed + failed + warnings

    print(f"\n  Total checks: {total}")
    print(f"  PASS:  {passed}")
    print(f"  FAIL:  {failed}")
    print(f"  WARN:  {warnings}")

    # Key recommendations
    print("\n  KEY FINDINGS:")
    vision_direct_ok = any("llama-vision" in r["category"] and r["status"] == "pass" for r in RESULTS)
    vision_shim_ok = any("shim-vision" in r["category"] and r["status"] == "pass" for r in RESULTS)

    if not vision_direct_ok:
        print("  !! llama.cpp direct vision FAILED")
        print("  -> Add --mmproj to your llama-server systemd service")
        print("  -> See: systemd/llamacpp.service in this repo")
    elif vision_direct_ok and not vision_shim_ok:
        print("  !! llama.cpp vision works, but shim fails")
        print("  -> Check SHIM_URL and docker-compose networking")
    elif vision_direct_ok and vision_shim_ok:
        print("  Vision pipeline is WORKING!")

    brave_ok = any("brave-cdp" in r["category"] and r["status"] == "pass" for r in RESULTS)
    if not brave_ok:
        print("  !! Brave CDP not reachable")
        print("  -> Start Brave: start-brave.sh")
        print("  -> Or: systemctl --user start brave-cdp.service")


async def save_report():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/captcha-test-report-{ts}.txt"
    with open(path, "w") as f:
        f.write(f"CAPTCHA Stack Test Report - {datetime.now()}\n")
        f.write(f"LLAMACPP_URL: {LLAMACPP_URL}\n")
        f.write(f"SHIM_URL: {SHIM_URL}\n")
        f.write(f"BRIDGE_URL: {BRIDGE_URL}\n")
        f.write(f"WHISPER_URL: {WHISPER_URL}\n")
        f.write(f"VISION_MODEL: {VISION_MODEL}\n")
        f.write("=" * 70 + "\n\n")
        for r in RESULTS:
            f.write(f"[{r['time']}] [{r['status'].upper():7}] [{r['category']:20}] {r['message']}\n")
    print(f"\n  Full report saved to: {path}")
    return path


async def main():
    print("=" * 70)
    print("  CAPTCHA SOLVING STACK - FULL SERVICE TEST")
    print(f"  Started: {datetime.now()}")
    print("=" * 70)

    # Run all tests
    await test_llamacpp_health()
    await test_llamacpp_models()
    await test_llamacpp_text_chat()
    await test_llamacpp_vision_chat()
    await test_shim_health()
    await test_shim_models()
    await test_shim_vision()
    await test_bridge_health()
    await test_whisper()
    await test_brave_cdp()

    # Optional hCaptcha test
    do_hcaptcha = input("\nRun hCaptcha screenshot + vision test? (requires Brave) [y/N]: ").lower().strip() == "y"
    if do_hcaptcha:
        await test_hcaptcha_screenshot()

    print_summary()
    report_path = await save_report()

    print(f"\n  Next steps:")
    print(f"  1. Check the report: cat {report_path}")
    print(f"  2. If vision fails, fix llama.cpp: see systemd/llamacpp.service")
    print(f"  3. Deploy changes: docker compose build && docker compose up -d")

    await http_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
