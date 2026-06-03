import os
import asyncio
import base64
import uuid
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

app = FastAPI(title="Captcha Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SHIM_URL = os.getenv("SHIM_URL", "http://captcha-solver:8000")
CDP_URL = os.getenv("CDP_URL", "http://host.docker.internal:9222")
CAPTCHA_RETRIES = int(os.getenv("CAPTCHA_RETRIES", "3"))
CAPTCHA_TIMEOUT = int(os.getenv("CAPTCHA_TIMEOUT", "60"))
BROWSER_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "30"))

# In-memory task store
tasks = {}


@app.get("/api/v1/health")
async def health():
    shim_ok = False
    cdp_ok = False
    try:
        r = await httpx.AsyncClient(timeout=5).get(f"{SHIM_URL}/health")
        shim_ok = r.status_code == 200
    except Exception:
        pass
    try:
        r = await httpx.AsyncClient(timeout=5).get(f"{CDP_URL}/json/version")
        cdp_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "status": "ok",
        "shim_reachable": shim_ok,
        "cdp_reachable": cdp_ok,
        "shim_url": SHIM_URL,
        "cdp_url": CDP_URL,
    }


@app.post("/createTask")
async def create_task(body: dict):
    task = body.get("task", {})
    task_type = task.get("type", "")

    # Image tasks -> forward to shim immediately (synchronous)
    if task_type in ("ImageToTextTask", "ImageToTextTaskMuggle", "ImageToTextTaskM1"):
        return await handle_image_task(task)

    # reCAPTCHA v2 image classification -> use CDP + vision
    if task_type == "ReCaptchaV2Classification":
        return await handle_recaptcha_v2_image(task)

    # Token tasks -> async via CDP, return taskId for polling
    if task_type in (
        "RecaptchaV3TaskProxyless",
        "RecaptchaV3TaskProxylessM1",
        "RecaptchaV3TaskProxylessM1S7",
        "RecaptchaV3TaskProxylessM1S9",
        "RecaptchaV3EnterpriseTask",
        "RecaptchaV3EnterpriseTaskM1",
        "NoCaptchaTaskProxyless",
        "RecaptchaV2TaskProxyless",
        "RecaptchaV2EnterpriseTaskProxyless",
        "HCaptchaTaskProxyless",
        "TurnstileTaskProxyless",
        "TurnstileTaskProxylessM1",
    ):
        task_id = str(uuid.uuid4())
        asyncio.create_task(solve_token_task_async(task_id, task_type, task))
        return {"errorId": 0, "taskId": task_id, "status": "processing"}

    return {
        "errorId": 1,
        "errorCode": "ERROR_UNKNOWN_TASK_TYPE",
        "errorDescription": f"Unsupported: {task_type}",
    }


@app.post("/getTaskResult")
async def get_task_result(body: dict):
    task_id = body.get("taskId", "")
    if task_id in tasks:
        result = tasks.pop(task_id)
        if result.get("errorId", 0) != 0:
            return result
        return {"errorId": 0, "status": "ready", "solution": result.get("solution", {})}
    return {"errorId": 0, "status": "processing"}


@app.get("/getBalance")
async def get_balance():
    return {"errorId": 0, "balance": 999.99}


# ── Image task handler ──
async def handle_image_task(task):
    image_b64 = task.get("body", "")
    instruction = "Read the text in this CAPTCHA image"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{SHIM_URL}/solve-json",
                json={"image": image_b64, "instruction": instruction},
            )
            data = r.json()
            if data.get("success"):
                return {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"text": data.get("answer", "")},
                }
            return {
                "errorId": 1,
                "errorCode": "ERROR_SHIM_FAILED",
                "errorDescription": data.get("error", "Shim error"),
            }
    except Exception as e:
        return {"errorId": 1, "errorCode": "ERROR_SHIM_FAILED", "errorDescription": str(e)}


# ── reCAPTCHA v2 image grid via CDP + vision ──
async def handle_recaptcha_v2_image(task):
    url = task.get("websiteURL", task.get("url", ""))

    if not url:
        return {
            "errorId": 1,
            "errorCode": "ERROR_BAD_PARAMETERS",
            "errorDescription": "Missing URL",
        }

    context = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = await browser.new_context(viewport={"width": 1280, "height": 900})
            page = await context.new_page()

            await page.goto(url, wait_until="networkidle", timeout=BROWSER_TIMEOUT * 1000)

            # Click the "I'm not a robot" checkbox
            try:
                checkbox = page.frame_locator(
                    'iframe[src*="recaptcha/api2/anchor"]'
                ).locator(".recaptcha-checkbox-border")
                await checkbox.click(timeout=5000)
                await asyncio.sleep(2)
            except (PWTimeout, Exception):
                pass

            token = await _solve_recaptcha_v2_image_grid(page)
            if token:
                return {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": token},
                }
            return {
                "errorId": 1,
                "errorCode": "ERROR_TOKEN_NOT_FOUND",
                "errorDescription": "Image grid solved but token not generated after retries",
            }

    except Exception as e:
        traceback.print_exc()
        return {
            "errorId": 1,
            "errorCode": "ERROR_CDP_FAILED",
            "errorDescription": str(e)[:200],
        }
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass


async def _wait_for_recaptcha_token(page, timeout_ms=30000):
    return await page.evaluate(
        f"""
        new Promise((resolve) => {{
            let interval = setInterval(() => {{
                let ta = document.querySelector('textarea[name="g-recaptcha-response"]');
                if (ta && ta.value) {{ clearInterval(interval); resolve(ta.value); }}
            }}, 500);
            setTimeout(() => {{ clearInterval(interval); resolve(null); }}, {timeout_ms});
        }})
    """
    )


async def _solve_recaptcha_v2_image_grid(page):
    """Handle reCAPTCHA v2 image grid challenges via CDP + vision.
    Returns the g-recaptcha token string, or None if unsolved.
    """
    for attempt in range(CAPTCHA_RETRIES):
        try:
            challenge_frame = page.frame_locator('iframe[src*="recaptcha/api2/bframe"]')
            await challenge_frame.locator(".rc-imageselect-table").wait_for(timeout=15000)
        except PWTimeout:
            # No image challenge visible - try direct token
            return await _wait_for_recaptcha_token(page, timeout_ms=10000)

        # Get instruction text
        try:
            instruction_el = challenge_frame.locator(".rc-imageselect-instructions")
            instruction_text = await instruction_el.inner_text()
            instruction = (
                f"{instruction_text.strip()}. "
                "Return ONLY comma-separated tile numbers like 1,3,6."
            )
        except Exception:
            instruction = (
                "Select all images containing the requested object. "
                "Return ONLY comma-separated tile numbers like 1,3,6."
            )

        # Screenshot the grid
        try:
            grid = challenge_frame.locator(".rc-imageselect-table")
            screenshot_bytes = await grid.screenshot()
            b64 = base64.b64encode(screenshot_bytes).decode()
        except Exception:
            return None

        # Send to shim for vision solving
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    f"{SHIM_URL}/solve-json",
                    json={"image": b64, "instruction": instruction},
                )
                data = r.json()
            if not data.get("success"):
                continue
            answer = data.get("answer", "")
        except Exception:
            continue

        # Parse and click tiles
        tiles = [t.strip() for t in answer.split(",") if t.strip().isdigit()]
        tile_locators = challenge_frame.locator(".rc-imageselect-tile")
        count = await tile_locators.count()

        for tile_num in tiles:
            try:
                idx = int(tile_num) - 1
                if 0 <= idx < count:
                    await tile_locators.nth(idx).click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass

        # Click verify
        try:
            await challenge_frame.locator("#recaptcha-verify-button").click()
            await asyncio.sleep(3)
        except Exception:
            pass

        # Check if we got a token
        token = await _wait_for_recaptcha_token(page, timeout_ms=10000)
        if token:
            return token
        # Otherwise loop - reCAPTCHA may present a new grid

    return None


# ── Token tasks (async background) ──
async def solve_token_task_async(task_id, task_type, task):
    url = task.get("websiteURL", task.get("url", ""))
    sitekey = task.get("websiteKey", task.get("sitekey", ""))

    if not url or not sitekey:
        tasks[task_id] = {
            "errorId": 1,
            "errorCode": "ERROR_BAD_PARAMETERS",
            "errorDescription": "Missing URL or sitekey",
        }
        return

    context = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900}
            )
            page = await context.new_page()

            await page.goto(url, wait_until="networkidle", timeout=BROWSER_TIMEOUT * 1000)

            if "RecaptchaV3" in task_type:
                token = await page.evaluate(
                    f"""
                    new Promise((resolve, reject) => {{
                        if (typeof grecaptcha === 'undefined') reject('grecaptcha not found');
                        grecaptcha.ready(() => {{
                            grecaptcha.execute('{sitekey}', {{
                                action: '{task.get("pageAction", "verify")}'
                            }}).then(resolve).catch(reject);
                        }});
                    }})
                    """,
                    timeout=30000,
                )
                tasks[task_id] = {
                    "errorId": 0,
                    "solution": {"gRecaptchaResponse": token},
                }

            elif "RecaptchaV2" in task_type:
                try:
                    checkbox = page.frame_locator(
                        'iframe[src*="recaptcha/api2/anchor"]'
                    ).locator(".recaptcha-checkbox-border")
                    await checkbox.click(timeout=5000)
                except Exception:
                    pass
                await asyncio.sleep(2)
                # Check for image grid challenge
                token = await _solve_recaptcha_v2_image_grid(page)
                if token:
                    tasks[task_id] = {
                        "errorId": 0,
                        "solution": {"gRecaptchaResponse": token},
                    }
                else:
                    tasks[task_id] = {
                        "errorId": 1,
                        "errorCode": "ERROR_TOKEN_NOT_FOUND",
                        "errorDescription": "reCAPTCHA v2 token not found",
                    }

            elif "HCaptcha" in task_type:
                try:
                    await page.frame_locator('iframe[src*="hcaptcha"]').locator(
                        "#checkbox"
                    ).click(timeout=5000)
                except Exception:
                    pass
                token = await page.evaluate(
                    """
                    new Promise((resolve) => {
                        let interval = setInterval(() => {
                            let ta = document.querySelector('textarea[name="h-captcha-response"]');
                            if (ta && ta.value) { clearInterval(interval); resolve(ta.value); }
                        }, 500);
                        setTimeout(() => { clearInterval(interval); resolve(null); }, 30000);
                    })
                    """
                )
                if token:
                    tasks[task_id] = {"errorId": 0, "solution": {"token": token}}
                else:
                    tasks[task_id] = {
                        "errorId": 1,
                        "errorCode": "ERROR_TOKEN_NOT_FOUND",
                        "errorDescription": "hCaptcha token not found",
                    }

            elif "Turnstile" in task_type:
                token = await page.evaluate(
                    """
                    new Promise((resolve) => {
                        let interval = setInterval(() => {
                            let ta = document.querySelector('input[name="cf-turnstile-response"]');
                            if (ta && ta.value) { clearInterval(interval); resolve(ta.value); }
                        }, 500);
                        setTimeout(() => { clearInterval(interval); resolve(null); }, 30000);
                    })
                    """
                )
                if token:
                    tasks[task_id] = {"errorId": 0, "solution": {"token": token}}
                else:
                    tasks[task_id] = {
                        "errorId": 1,
                        "errorCode": "ERROR_TOKEN_NOT_FOUND",
                        "errorDescription": "Turnstile token not found",
                    }

            else:
                tasks[task_id] = {
                    "errorId": 1,
                    "errorCode": "ERROR_UNKNOWN_TASK_TYPE",
                    "errorDescription": f"Token type not implemented: {task_type}",
                }

    except Exception as e:
        traceback.print_exc()
        tasks[task_id] = {
            "errorId": 1,
            "errorCode": "ERROR_CDP_FAILED",
            "errorDescription": str(e)[:200],
        }
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
