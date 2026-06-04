import os, base64, json, time, asyncio, logging
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from PIL import Image
import io

# ── Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("captcha-solver")

app = FastAPI(title="Captcha Solver Shim")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LLAMACPP_URL = os.getenv("LLAMACPP_URL", "https://llamacpp.xyxxyyxy.dev")
VISION_MODEL = os.getenv("VISION_MODEL", "Qwen3VL-8B-Instruct-Q8_0")
UNLOAD_AFTER_SOLVE = os.getenv("UNLOAD_AFTER_SOLVE", "false").lower() == "true"

log.info("=== CAPTCHA SOLVER SHIM START ===")
log.info("LLAMACPP_URL=%s", LLAMACPP_URL)
log.info("VISION_MODEL=%s", VISION_MODEL)
log.info("UNLOAD_AFTER_SOLVE=%s", UNLOAD_AFTER_SOLVE)

http_client = httpx.AsyncClient(timeout=300.0, follow_redirects=True)

@app.get("/health")
async def health():
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/health")
        llama_status = "ok" if r.status_code == 200 else f"error_{r.status_code}"
    except Exception as e:
        llama_status = f"unreachable: {str(e)[:80]}"

    try:
        r2 = await http_client.get(f"{LLAMACPP_URL}/models")
        models_data = r2.json() if r2.status_code == 200 else {}
        if isinstance(models_data, dict) and "data" in models_data:
            current = models_data.get("data", [{}])[0].get("id", "none") if models_data.get("data") else "none"
        else:
            current = "unknown"
    except Exception as e:
        current = f"unknown ({e})"

    return {
        "shim_status": "ok",
        "llamacpp_url": LLAMACPP_URL,
        "llamacpp_status": llama_status,
        "vision_model_target": VISION_MODEL,
        "currently_loaded": current,
        "unload_after_solve": UNLOAD_AFTER_SOLVE
    }

@app.post("/swap-model")
async def swap_model(model: str = Form(VISION_MODEL)):
    return await _ensure_model_loaded(model)

@app.post("/solve")
async def solve(
    file: UploadFile = File(...),
    instruction: str = Form("Solve this CAPTCHA"),
    model: str = Form(VISION_MODEL)
):
    log.info("[/solve] Received solve request: model=%s instruction=%s", model, instruction[:50])

    # Ensure vision model is loaded
    log.info("[/solve] Ensuring model %s is loaded...", model)
    load_result = await _ensure_model_loaded(model)
    log.info("[/solve] Model load result: %s", load_result)
    if not load_result.get("success"):
        raise HTTPException(status_code=502, detail=f"llama.cpp refused to load model: {load_result.get('error')}")

    # Read and convert image
    contents = await file.read()
    log.info("[/solve] Uploaded file: %d bytes", len(contents))
    try:
        img = Image.open(io.BytesIO(contents))
        log.info("[/solve] Image format=%s mode=%s size=%s", img.format, img.mode, img.size)
        # Convert to RGB if necessary
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if too large (keep under model context)
        max_size = 512  # REDUCED: smaller images use less context window
        orig_size = img.size
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size))
            log.info("[/solve] Resized image: %s -> %s", orig_size, img.size)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        log.info("[/solve] Final image: %d bytes base64", len(b64))
    except Exception as e:
        log.error("[/solve] Image processing failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Image processing failed: {e}")

    # Call llama.cpp vision
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a CAPTCHA solver. Analyze the image and respond ONLY with the answer."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 100
    }

    log.info("[/solve] Sending to llama.cpp /v1/chat/completions...")
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        log.info("[/solve] llama.cpp response status: %d", r.status_code)
        r.raise_for_status()
        data = r.json()
        answer = data["choices"][0]["message"]["content"].strip()
        log.info("[/solve] Answer (first 100 chars): %s", answer[:100])
    except Exception as e:
        log.error("[/solve] llama.cpp inference error: %s", e)
        if UNLOAD_AFTER_SOLVE:
            await _unload_model()
        raise HTTPException(status_code=502, detail=f"llama.cpp inference error: {e}")

    if UNLOAD_AFTER_SOLVE:
        await _unload_model()

    return {"success": True, "answer": answer, "model_used": model, "error": None}

# JSON endpoint for extension direct calls
@app.post("/solve-json")
async def solve_json(body: dict):
    image_b64 = body.get("image", "")
    instruction = body.get("instruction", "Solve this CAPTCHA")
    model = body.get("model", VISION_MODEL)

    log.info("[/solve-json] Received request: model=%s instruction=%s image_len=%d",
             model, instruction[:50], len(image_b64))

    load_result = await _ensure_model_loaded(model)
    log.info("[/solve-json] Model load result: %s", load_result)
    if not load_result.get("success"):
        raise HTTPException(status_code=502, detail=f"llama.cpp refused to load model: {load_result.get('error')}")

    # Resize image if needed
    try:
        img_data = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_data))
        log.info("[/solve-json] Image format=%s mode=%s size=%s", img.format, img.mode, img.size)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        max_size = 512
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size))
            log.info("[/solve-json] Resized to %s", img.size)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_b64 = base64.b64encode(buf.getvalue()).decode()
            log.info("[/solve-json] Resized base64 length: %d", len(image_b64))
    except Exception as e:
        log.warning("[/solve-json] Image resize failed (continuing with original): %s", e)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a CAPTCHA solver. Analyze the image and respond ONLY with the answer."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 100
    }

    log.info("[/solve-json] Sending to llama.cpp...")
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        log.info("[/solve-json] llama.cpp response: %d", r.status_code)
        r.raise_for_status()
        data = r.json()
        answer = data["choices"][0]["message"]["content"].strip()
        log.info("[/solve-json] Answer: %s", answer[:100])
    except Exception as e:
        log.error("[/solve-json] llama.cpp error: %s", e)
        if UNLOAD_AFTER_SOLVE:
            await _unload_model()
        raise HTTPException(status_code=502, detail=f"llama.cpp inference error: {e}")

    if UNLOAD_AFTER_SOLVE:
        await _unload_model()

    return {"success": True, "answer": answer, "model_used": model, "error": None}

def _model_names_match(name1: str, name2: str) -> bool:
    """Flexible model name matching.
    
    Handles differences like:
      'Qwen3VL 8B Q8_0 Instruct' == 'Qwen3VL-8B-Instruct-Q8_0'
    By normalizing: lowercase, remove all non-alphanumeric, compare.
    """
    if not name1 or not name2:
        return False
    n1 = ''.join(c.lower() for c in name1 if c.isalnum())
    n2 = ''.join(c.lower() for c in name2 if c.isalnum())
    # Check if the core identifiers match (qwen3vl + 8b + q8_0)
    return n1 == n2 or (len(n1) > 6 and len(n2) > 6 and (n1 in n2 or n2 in n1))


async def _ensure_model_loaded(target_model: str):
    import traceback
    log.info("[_ensure_model] Checking if model '%s' is loaded...", target_model)

    # Check current model - look at ALL models returned
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/models")
        log.info("[_ensure_model] /models response: %d", r.status_code)
        data = r.json()
        models = data.get("data", [])
        
        # Log ALL models in the response
        log.info("[_ensure_model] Full /models data: %s", json.dumps(data, indent=2)[:800])
        
        # Check every model in the list for a match
        for m in models:
            if isinstance(m, dict):
                current = m.get("id", "")
            elif isinstance(m, str):
                current = m
            else:
                continue
            log.info("[_ensure_model] Checking model: '%s' vs target '%s'", current, target_model)
            if current == target_model or _model_names_match(current, target_model):
                log.info("[_ensure_model] MATCH: Model '%s' is already loaded (flexible match)", current)
                return {"success": True, "action": "already_loaded", "model": current}
        
        # No match found
        if models:
            first = models[0].get("id", "") if isinstance(models[0], dict) else str(models[0])
            log.info("[_ensure_model] No match. First model: '%s', target: '%s'", first, target_model)
        else:
            log.info("[_ensure_model] No models returned from /models")
    except Exception as e:
        log.warning("[_ensure_model] Model check failed: %s: %s", type(e).__name__, e)

    # Try to unload current model (best effort - don't fail if it doesn't work)
    log.info("[_ensure_model] Attempting to unload current model...")
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/models/unload")
        log.info("[_ensure_model] Unload response: %d", r.status_code)
        if r.status_code == 200:
            await asyncio.sleep(1)
        else:
            log.info("[_ensure_model] Unload returned %d (may be a single-model server)", r.status_code)
    except Exception as e:
        log.info("[_ensure_model] Unload failed (non-fatal): %s", e)

    # Load target model
    log.info("[_ensure_model] Loading model '%s'...", target_model)
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/models/load", json={"model": target_model})
        log.info("[_ensure_model] Load response: %d", r.status_code)
        if r.status_code == 200:
            log.info("[_ensure_model] Polling until model is ready...")
            for i in range(30):
                await asyncio.sleep(2)
                try:
                    r2 = await http_client.get(f"{LLAMACPP_URL}/models")
                    data2 = r2.json()
                    for m in data2.get("data", []):
                        current = m.get("id", "") if isinstance(m, dict) else str(m)
                        if current == target_model or _model_names_match(current, target_model):
                            log.info("[_ensure_model] Model '%s' confirmed after %d polls", current, i + 1)
                            return {"success": True, "action": "loaded", "model": current}
                except Exception:
                    pass
            log.warning("[_ensure_model] Model load timeout, proceeding anyway")
            return {"success": True, "action": "loaded_timeout", "model": target_model}
        elif r.status_code == 400:
            text = (await r.aread()).decode('utf-8', errors='replace')
            log.info("[_ensure_model] Load returned 400: %s", text[:300])
            if "already" in text.lower() or "running" in text.lower():
                log.info("[_ensure_model] Model is already running, proceeding")
                return {"success": True, "action": "already_loaded", "model": target_model}
            return {"success": False, "error": text}
        else:
            text = (await r.aread()).decode('utf-8', errors='replace')
            log.error("[_ensure_model] Load failed: HTTP %d: %s", r.status_code, text[:500])
            return {"success": False, "error": f"HTTP {r.status_code}: {text}"}
    except Exception as e:
        err_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        log.error("[_ensure_model] Load exception: %s", err_detail[:500])
        return {"success": False, "error": f"{type(e).__name__}: {e}"}

async def _unload_model():
    try:
        await http_client.post(f"{LLAMACPP_URL}/models/unload")
    except:
        pass

# ── OpenAI-compatible proxy endpoints (needed by OhMyCaptcha) ──

@app.get("/v1/models")
async def list_models():
    """Proxy to llama.cpp /models endpoint."""
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/models")
        log.info("[/v1/models] Proxy status: %d", r.status_code)
        return r.json() if r.status_code == 200 else {"data": [{"id": VISION_MODEL}]}
    except Exception as e:
        log.warning("[/v1/models] Proxy failed: %s", e)
        return {"data": [{"id": VISION_MODEL, "object": "model"}]}

@app.post("/v1/chat/completions")
async def chat_completions(body: dict):
    """Proxy chat completions to llama.cpp for text/vision tasks."""
    target_model = body.get("model", VISION_MODEL)
    log.info("[/v1/chat/completions] model=%s messages=%d",
             target_model, len(body.get("messages", [])))

    # Log message content types (text vs image)
    for i, msg in enumerate(body.get("messages", [])):
        content = msg.get("content", "")
        if isinstance(content, list):
            types = [c.get("type") for c in content]
            log.info("[/v1/chat/completions] Message %d types: %s", i, types)
            for j, c in enumerate(content):
                if c.get("type") == "image_url":
                    url = c.get("image_url", {}).get("url", "")
                    log.info("[/v1/chat/completions] Message %d image %d: url_len=%d",
                             i, j, len(url))
        else:
            log.info("[/v1/chat/completions] Message %d: text_len=%d", i, len(str(content)))

    # Ensure model is loaded before forwarding
    log.info("[/v1/chat/completions] Ensuring model %s is loaded...", target_model)
    load_result = await _ensure_model_loaded(target_model)
    log.info("[/v1/chat/completions] Model load: %s", load_result.get("action", "unknown"))
    if not load_result.get("success"):
        log.error("[/v1/chat/completions] Model load failed: %s", load_result.get("error"))
        raise HTTPException(status_code=502, detail=f"Model load failed: {load_result.get('error')}")

    # Check for oversized images in the payload and resize them
    body = _resize_images_in_payload(body)

    log.info("[/v1/chat/completions] Forwarding to llama.cpp...")
    try:
        r = await http_client.post(
            f"{LLAMACPP_URL}/v1/chat/completions",
            json=body,
            timeout=300.0
        )
        log.info("[/v1/chat/completions] llama.cpp response: %d", r.status_code)
        if r.status_code != 200:
            err_text = r.text[:500]
            log.error("[/v1/chat/completions] llama.cpp error body: %s", err_text)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.error("[/v1/chat/completions] HTTP error: %s", e)
        raise HTTPException(status_code=502, detail=f"llama.cpp error: {e}")
    finally:
        if UNLOAD_AFTER_SOLVE:
            await _unload_model()

def _resize_images_in_payload(body: dict) -> dict:
    """Resize any large images in the payload to reduce context window usage."""
    max_size = 512  # Max dimension in pixels
    for msg in body.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:image"):
                        try:
                            # Extract base64 from data URL
                            header, b64data = url.split(",", 1)
                            img_bytes = base64.b64decode(b64data)
                            orig_kb = len(img_bytes) // 1024
                            img = Image.open(io.BytesIO(img_bytes))
                            if img.mode in ("RGBA", "P"):
                                img = img.convert("RGB")
                            if max(img.size) > max_size:
                                old_size = img.size
                                img.thumbnail((max_size, max_size))
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                new_b64 = base64.b64encode(buf.getvalue()).decode()
                                new_kb = len(buf.getvalue()) // 1024
                                item["image_url"]["url"] = f"data:image/png;base64,{new_b64}"
                                log.info("[/v1/chat/completions] Resized image: %s (%dKB) -> %s (%dKB)",
                                         old_size, orig_kb, img.size, new_kb)
                        except Exception as e:
                            log.warning("[/v1/chat/completions] Image resize failed: %s", e)
    return body

WHISPER_URL = os.getenv("WHISPER_URL", "http://whisper:1233")
log.info("WHISPER_URL=%s", WHISPER_URL)

@app.post("/v1/audio/transcriptions")
async def audio_transcription(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str = Form("en"),
    prompt: str = Form("Transcribe the spoken digits. Reply with digits only, separated by spaces.")
):
    """Proxy audio transcription to whisperfile.
    OhMyCaptcha's reCAPTCHA v2 solver calls this for audio challenge transcription."""
    contents = await file.read()
    log.info("[/v1/audio/transcriptions] Received: %d bytes, model=%s, lang=%s", len(contents), model, language)
    try:
        r = await http_client.post(
            f"{WHISPER_URL}/v1/audio/transcriptions",
            files={"file": (file.filename, contents, file.content_type or "audio/mpeg")},
            data={"model": model, "language": language},
            timeout=60.0
        )
        log.info("[/v1/audio/transcriptions] Whisper response: %d", r.status_code)
        r.raise_for_status()
        result = r.json()
        log.info("[/v1/audio/transcriptions] Transcript: %s", result.get("text", "")[:100])
        return result
    except httpx.HTTPError as e:
        log.error("[/v1/audio/transcriptions] Whisper error: %s", e)
        raise HTTPException(status_code=502, detail=f"Whisperfile error: {e}")

@app.get("/v1/audio/transcriptions")
async def audio_transcription_info():
    """Health check for whisperfile transcription endpoint."""
    try:
        r = await http_client.get(f"{WHISPER_URL}/health", timeout=5.0)
        return {"whisper_url": WHISPER_URL, "whisper_status": "ok" if r.status_code == 200 else f"error_{r.status_code}"}
    except Exception as e:
        return {"whisper_url": WHISPER_URL, "whisper_status": f"error: {str(e)[:100]}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
