#!/usr/bin/env python3
"""
End-to-end CAPTCHA solving tests against live demo sites.

Tests the FULL pipeline:
  1. Navigate to real CAPTCHA demo page in Brave
  2. Send task to captcha-bridge API
  3. Bridge controls Brave via CDP to solve
  4. Poll for result
  5. Verify token obtained

Demo sites used:
  - hCaptcha: https://accounts.hcaptcha.com/demo
  - reCAPTCHA v2: https://www.google.com/recaptcha/api2/demo

Usage:
  python3 test_e2e_captcha.py              # Run all tests
  python3 test_e2e_captcha.py --hcaptcha   # hCaptcha only
  python3 test_e2e_captcha.py --recaptcha  # reCAPTCHA v2 only
  python3 test_e2e_captcha.py --debug      # Extra verbose output
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("e2e-test")

BRIDGE_URL = "http://localhost:1231"
SHIM_URL = "http://localhost:1232"
VISION_URL = "http://localhost:6663"
CDP_URL = "http://localhost:9222"

http_client = httpx.AsyncClient(timeout=120.0)

# ── Color output ──
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

PASS = 0
FAIL = 0


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def check(name, ok, msg=""):
    global PASS, FAIL
    status = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    detail = f" - {msg}" if msg else ""
    print(f"  [{status}] {name}{detail}")
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


# ── Helpers ──

async def check_prerequisites():
    """Check all required services are running."""
    section("PREREQUISITES")
    all_ok = True

    # Vision server
    try:
        r = await http_client.get(f"{VISION_URL}/health", timeout=5.0)
        check("Vision server (6663)", r.status_code == 200)
    except Exception as e:
        check("Vision server (6663)", False, str(e))
        all_ok = False

    # Shim
    try:
        r = await http_client.get(f"{SHIM_URL}/stats", timeout=5.0)
        check("Shim (1232)", r.status_code == 200)
    except Exception as e:
        check("Shim (1232)", False, str(e))
        all_ok = False

    # Bridge
    try:
        r = await http_client.get(f"{BRIDGE_URL}/api/v1/health", timeout=5.0)
        check("Bridge (1231)", r.status_code == 200)
    except Exception as e:
        check("Bridge (1231)", False, str(e))
        all_ok = False

    # Brave CDP
    try:
        r = await http_client.get(f"{CDP_URL}/json/version", timeout=5.0)
        check("Brave CDP (9222)", r.status_code == 200)
    except Exception as e:
        check("Brave CDP (9222)", False, str(e))
        all_ok = False

    if not all_ok:
        print(f"\n{YELLOW}Prerequisites not met. Fix services first:{RESET}")
        print("  docker compose up -d")
        print("  systemctl --user status brave-cdp")
        return False
    return True


async def send_task(task_type, website_url, website_key, **extra):
    """Send a task to the bridge and return task_id."""
    payload = {
        "clientKey": "local",
        "task": {
            "type": task_type,
            "websiteURL": website_url,
            "websiteKey": website_key,
            **extra,
        },
    }
    log.info("Creating %s task for %s", task_type, website_url)
    try:
        r = await http_client.post(f"{BRIDGE_URL}/createTask", json=payload, timeout=30.0)
        data = r.json()
        if data.get("errorId", 0) != 0:
            log.error("Bridge error: %s", data.get("errorDescription", "unknown"))
            return None
        task_id = data.get("taskId")
        log.info("Task created: %s", task_id)
        return task_id
    except Exception as e:
        log.error("Failed to create task: %s", e)
        return None


async def poll_task_result(task_id, max_wait=180):
    """Poll bridge for task result with extended timeout for CAPTCHA solving."""
    log.info("Polling for result (max %ds - CAPTCHA solving takes time)...", max_wait)
    start = time.time()
    last_progress = 0
    while time.time() - start < max_wait:
        try:
            r = await http_client.post(
                f"{BRIDGE_URL}/getTaskResult",
                json={"clientKey": "local", "taskId": task_id},
                timeout=10.0,
            )
            data = r.json()
            status = data.get("status", "processing")
            elapsed = time.time() - start

            if status == "ready":
                token = data.get("solution", {}).get("gRecaptchaResponse", "")
                if token and len(token) > 20:
                    log.info("Token received (len=%d) after %.0fs", len(token), elapsed)
                    return token
                log.warning("Empty token in ready response")
                return None
            elif status == "failed":
                err = data.get("errorDescription", "unknown")
                log.error("Task failed after %.0fs: %s", elapsed, err)
                return None

            # Progress update every 30 seconds
            if int(elapsed) - last_progress >= 30:
                log.info("Still processing... (%.0fs elapsed)", elapsed)
                log.info("  Check bridge logs: docker logs --tail 10 captcha-bridge")
                last_progress = int(elapsed)

            await asyncio.sleep(3)
        except Exception as e:
            log.warning("Poll error: %s", e)
            await asyncio.sleep(3)

    log.error("Timeout after %ds. The solver may have:", max_wait)
    log.error("  - Failed to interact with the challenge")
    log.error("  - Been blocked by bot detection")
    log.error("  - Had vision model errors")
    log.error("Check: docker logs --tail 50 captcha-bridge")
    return None


# ── Test: hCaptcha ──

async def test_hcaptcha():
    section("hCaptcha E2E Test")
    print("  Target: https://accounts.hcaptcha.com/demo")

    site_key = "10000000-ffff-ffff-ffff-000000000001"  # hCaptcha demo key

    task_id = await send_task(
        "HCaptchaTaskProxyless",
        "https://accounts.hcaptcha.com/demo",
        site_key,
    )
    if not task_id:
        check("Task creation", False, "Failed to create task")
        return False

    check("Task creation", True, f"ID: {task_id[:8]}")

    token = await poll_task_result(task_id, max_wait=180)
    if token:
        check("Token obtained", True, f"len={len(token)}")
        log.info("Token preview: %s...", token[:60])
        return True
    else:
        check("Token obtained", False, "Solver timed out - check bridge logs")
        return False


# ── Test: reCAPTCHA v2 ──

async def test_recaptcha_v2():
    section("reCAPTCHA v2 E2E Test")
    print("  Target: https://www.google.com/recaptcha/api2/demo")
    print("  NOTE: reCAPTCHA v2 audio often triggers 'automated queries' detection.")
    print("        If this test fails, the bot detection is active.")

    site_key = "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-"  # Google demo key

    task_id = await send_task(
        "RecaptchaV2TaskProxyless",
        "https://www.google.com/recaptcha/api2/demo",
        site_key,
    )
    if not task_id:
        check("Task creation", False, "Failed to create task")
        return False

    check("Task creation", True, f"ID: {task_id[:8]}")

    token = await poll_task_result(task_id, max_wait=180)
    if token:
        check("Token obtained", True, f"len={len(token)}")
        log.info("Token preview: %s...", token[:60])
        return True
    else:
        check("Token obtained", False, "Solver timed out or bot detection blocked")
        return False


# ── Test: Direct Vision (no bridge) ──

async def test_direct_vision():
    """Test vision model directly with a real challenge screenshot."""
    section("Direct Vision Model Test")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        check("Playwright available", False, "pip install playwright")
        return False

    print("  Navigating to hCaptcha demo for screenshot...")
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            contexts = browser.contexts
            if contexts and contexts[0].pages:
                page = contexts[0].pages[0]
            else:
                page = await (contexts[0].new_page() if contexts else browser.new_page())

            await page.goto("https://accounts.hcaptcha.com/demo", wait_until="domcontentloaded")
            await asyncio.sleep(1)

            # Click checkbox
            for f in page.frames:
                if f.url and "hcaptcha.com" in f.url and ("checkbox" in f.url or "anchor" in f.url):
                    try:
                        await f.evaluate("() => { const cb = document.querySelector('#checkbox'); if (cb) cb.click(); }")
                    except:
                        pass
                    break

            await asyncio.sleep(3)

            # Screenshot
            screenshot = await page.screenshot()
            print(f"  Screenshot: {len(screenshot)} bytes")

            # Save
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/e2e_hcaptcha_{ts}.png"
            with open(path, "wb") as f:
                f.write(screenshot)
            print(f"  Saved: {path}")

            # Resize and send to vision
            img = Image.open(io.BytesIO(screenshot))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            if max(img.size) > 512:
                img.thumbnail((512, 512))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()

            print(f"  Sending to local vision server ({len(b64)} bytes)...")

            payload = {
                "model": "Qwen3VL-8B-Instruct-Q4_K_M",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What does this CAPTCHA ask? Be brief."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }],
                "temperature": 0.1,
                "max_tokens": 200
            }

            r = await http_client.post(f"{VISION_URL}/v1/chat/completions", json=payload, timeout=60.0)
            check("Vision HTTP", r.status_code == 200, f"status={r.status_code}")

            if r.status_code == 200:
                data = r.json()
                answer = data["choices"][0]["message"]["content"]
                print(f"  Vision response: {answer[:200]}")
                check("Vision analysis", True, f"Got {len(answer)} chars")
                return True

            await browser.close()
    except Exception as e:
        check("Direct vision test", False, str(e))
        return False

    return False


# ── Main ──

async def main():
    parser = argparse.ArgumentParser(description="CAPTCHA E2E Tests")
    parser.add_argument("--hcaptcha", action="store_true", help="hCaptcha test only")
    parser.add_argument("--recaptcha", action="store_true", help="reCAPTCHA v2 test only")
    parser.add_argument("--vision", action="store_true", help="Direct vision test only")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 70)
    print("  CAPTCHA END-TO-END TESTS")
    print(f"  Started: {datetime.now()}")
    print("=" * 70)

    # Check prerequisites
    if not await check_prerequisites():
        print(f"\n{RED}Fix prerequisites and retry{RESET}")
        sys.exit(1)

    # Run requested tests (or all)
    results = {}

    if args.vision or not (args.hcaptcha or args.recaptcha):
        results["direct_vision"] = await test_direct_vision()

    if args.hcaptcha or not (args.recaptcha or args.vision):
        results["hcaptcha"] = await test_hcaptcha()

    if args.recaptcha or not (args.hcaptcha or args.vision):
        results["recaptcha_v2"] = await test_recaptcha_v2()

    # Summary
    section("SUMMARY")
    for name, ok in results.items():
        status = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"  [{status}] {name}")

    print(f"\n  Total: {PASS + FAIL} | {GREEN}Pass: {PASS}{RESET} | {RED}Fail: {FAIL}{RESET}")

    if FAIL > 0:
        print(f"\n{YELLOW}Diagnostics:{RESET}")
        print("  ./scripts/diagnose.sh")
        print("  docker logs -f captcha-bridge")
        print("  docker logs -f captcha-solver")
        print("  docker logs -f llamacpp-vision")
        sys.exit(1)
    else:
        print(f"\n{GREEN}All tests passed!{RESET}")

    await http_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
