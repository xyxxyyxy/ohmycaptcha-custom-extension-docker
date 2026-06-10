#!/usr/bin/env python3
"""Test script to diagnose vision model issues.

Tests:
1. Basic connectivity to llama.cpp /models endpoint
2. Text-only chat completion
3. Vision chat completion with a test image
4. Screenshot capture from hCaptcha demo
"""

import asyncio
import base64
import json
import sys

import httpx
from playwright.async_api import async_playwright

LLAMACPP_URL = "https://llamacpp.xyxxyyxy.dev"
VISION_MODEL = "Qwen3VL-8B-Instruct-Q4_K_M"
SHIM_URL = "http://localhost:1232"

http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)


async def test_models_endpoint():
    """Test 1: Check what model is loaded."""
    print("=" * 60)
    print("TEST 1: /models endpoint")
    print("=" * 60)
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/models")
        print(f"  Status: {r.status_code}")
        data = r.json()
        print(f"  Response: {json.dumps(data, indent=2)[:500]}")
        models = data.get("data", [])
        if models:
            current = models[0].get("id") if isinstance(models[0], dict) else models[0]
            print(f"  CURRENTLY LOADED: {current}")
            print(f"  TARGET: {VISION_MODEL}")
            if current != VISION_MODEL:
                print(f"  *** PROBLEM: Wrong model loaded! Need {VISION_MODEL}, have {current}")
        return data
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


async def test_model_unload():
    """Test 2: Try to unload current model."""
    print()
    print("=" * 60)
    print("TEST 2: /models/unload")
    print("=" * 60)
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/models/unload")
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.text[:200]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_model_load():
    """Test 3: Try to load vision model."""
    print()
    print("=" * 60)
    print("TEST 3: /models/load")
    print("=" * 60)
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/models/load", json={"model": VISION_MODEL})
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.text[:300]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_text_only():
    """Test 4: Text-only chat completion (no image)."""
    print()
    print("=" * 60)
    print("TEST 4: Text-only /v1/chat/completions")
    print("=" * 60)
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "user", "content": "What is 2+2? Answer with just the number."}
        ],
        "temperature": 0.1,
        "max_tokens": 10
    }
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            print(f"  Answer: {answer}")
        else:
            print(f"  Error body: {r.text[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_vision_small():
    """Test 5: Vision chat with tiny test image."""
    print()
    print("=" * 60)
    print("TEST 5: Vision /v1/chat/completions (tiny test image)")
    print("=" * 60)
    # Create a tiny 10x10 red PNG
    from PIL import Image
    import io
    img = Image.new("RGB", (10, 10), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    print(f"  Image size: {len(b64)} bytes base64")

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is this? Answer with one word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 10
    }
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            print(f"  Answer: {answer}")
        else:
            print(f"  Error body: {r.text[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_vision_shim():
    """Test 6: Vision via captcha-solver shim."""
    print()
    print("=" * 60)
    print("TEST 6: Vision via captcha-solver shim")
    print("=" * 60)
    from PIL import Image
    import io
    img = Image.new("RGB", (10, 10), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is this? Answer with one word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 10
    }
    try:
        r = await http_client.post(f"{SHIM_URL}/v1/chat/completions", json=payload)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            print(f"  Answer: {answer}")
        else:
            print(f"  Error body: {r.text[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_hcaptcha_screenshot():
    """Test 7: Capture hCaptcha screenshot and send to vision model."""
    print()
    print("=" * 60)
    print("TEST 7: hCaptcha screenshot + vision model")
    print("=" * 60)

    from PIL import Image
    import io

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
        else:
            page = await browser.new_page()

        await page.goto("https://accounts.hcaptcha.com/demo")
        await asyncio.sleep(2)

        # Click checkbox
        for f in page.frames:
            if f.url and "hcaptcha.com" in f.url and ("checkbox" in f.url or "anchor" in f.url):
                try:
                    await f.evaluate("() => { const cb = document.querySelector('#checkbox'); if (cb) cb.click(); }")
                    print("  Clicked checkbox")
                except:
                    pass
                break

        await asyncio.sleep(3)

        # Take screenshot
        screenshot = await page.screenshot()
        print(f"  Screenshot: {len(screenshot)} bytes")

        # Save for inspection
        with open("/tmp/hcaptcha_test.png", "wb") as f:
            f.write(screenshot)
        print("  Saved to /tmp/hcaptcha_test.png")

        # Resize and convert to base64
        img = Image.open(io.BytesIO(screenshot))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        max_size = 512
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size))
            print(f"  Resized to {img.size}")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        print(f"  Base64 length: {len(b64)}")

        # Send to vision model
        payload = {
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a CAPTCHA solver. Look at the image and identify which grid tiles match the prompt. Return ONLY a JSON array like [0, 2, 5] with 0-indexed tile numbers."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Click exactly the animals requested in the guide"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 100
        }

        print(f"  Sending to {LLAMACPP_URL}/v1/chat/completions...")
        try:
            r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
            print(f"  Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                answer = data["choices"][0]["message"]["content"]
                print(f"  Answer: {answer[:200]}")
            else:
                print(f"  Error body: {r.text[:500]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        await browser.close()


async def main():
    print("\n" + "=" * 60)
    print("VISION MODEL DIAGNOSTIC TESTS")
    print(f"Server: {LLAMACPP_URL}")
    print(f"Model: {VISION_MODEL}")
    print(f"Shim: {SHIM_URL}")
    print("=" * 60)

    await test_models_endpoint()
    await test_model_unload()
    await test_model_load()
    await test_text_only()
    await test_vision_small()
    await test_vision_shim()

    # Screenshot test (requires Brave running)
    print()
    print("=" * 60)
    print("NOTE: Test 7 requires Brave running with CDP on port 9222")
    print("      Run: start-brave.sh")
    print("=" * 60)
    do_screenshot = input("\nRun hCaptcha screenshot test? (y/N): ").lower().strip() == "y"
    if do_screenshot:
        await test_hcaptcha_screenshot()

    print("\n" + "=" * 60)
    print("DIAGNOSIS:")
    print("=" * 60)
    print("""
If tests 1-3 show:
  - Wrong model loaded (DeepSeek-OCR instead of Qwen3VL)
  - /models/unload returns 500
  - /models/load returns 400 "already running"
  
Then the llama.cpp server needs to be restarted with the correct model:
  1. Stop llama.cpp
  2. Start with: ./llama-server -m Qwen3VL-8B-Instruct-Q4_K_M.gguf ...
  3. Or configure with --models-max > 1 to allow model swapping

If test 4 (text-only) works but test 5 (vision) fails:
  - The loaded model doesn't support vision ( DeepSeek-OCR is text-only)
  - Need to load Qwen3VL-8B-Instruct-Q4_K_M which has vision capabilities

If test 5 works but test 6 (shim) fails:
  - The captcha-solver shim has a bug
  - Check shim logs: docker logs -f captcha-solver
""")


if __name__ == "__main__":
    asyncio.run(main())
