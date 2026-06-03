import os, base64, json, time, asyncio
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from PIL import Image
import io

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

http_client = httpx.AsyncClient(timeout=300.0, follow_redirects=True)

@app.get("/health")
async def health():
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/health")
        llama_status = "ok" if r.status_code == 200 else "error"
    except Exception as e:
        llama_status = f"unreachable: {str(e)[:50]}"

    try:
        r2 = await http_client.get(f"{LLAMACPP_URL}/models")
        models_data = r2.json() if r2.status_code == 200 else {}
        current = models_data.get("data", [{}])[0].get("id", "none") if isinstance(models_data, dict) and "data" in models_data else "unknown"
    except:
        current = "unknown"

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
    # Ensure vision model is loaded
    load_result = await _ensure_model_loaded(model)
    if not load_result.get("success"):
        raise HTTPException(status_code=502, detail=f"llama.cpp refused to load model: {load_result.get('error')}")

    # Read and convert image
    contents = await file.read()
    try:
        img = Image.open(io.BytesIO(contents))
        # Convert to RGB if necessary
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if too large (keep under model context)
        max_size = 1024
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
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

    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        answer = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
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

    load_result = await _ensure_model_loaded(model)
    if not load_result.get("success"):
        raise HTTPException(status_code=502, detail=f"llama.cpp refused to load model: {load_result.get('error')}")

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

    try:
        r = await http_client.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        answer = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        if UNLOAD_AFTER_SOLVE:
            await _unload_model()
        raise HTTPException(status_code=502, detail=f"llama.cpp inference error: {e}")

    if UNLOAD_AFTER_SOLVE:
        await _unload_model()

    return {"success": True, "answer": answer, "model_used": model, "error": None}

async def _ensure_model_loaded(target_model: str):
    # Check current model
    try:
        r = await http_client.get(f"{LLAMACPP_URL}/models")
        data = r.json()
        models = data.get("data", [])
        current = models[0].get("id", "") if models else ""
        if current == target_model:
            return {"success": True, "action": "already_loaded", "model": target_model}
    except Exception:
        pass

    # Unload current model first (needed when --models-max 1)
    try:
        await http_client.post(f"{LLAMACPP_URL}/models/unload")
        await asyncio.sleep(1)
    except Exception:
        pass

    # Load target model
    try:
        r = await http_client.post(f"{LLAMACPP_URL}/models/load", json={"model": target_model})
        if r.status_code == 200:
            # Poll until ready
            for _ in range(30):
                await asyncio.sleep(2)
                try:
                    r2 = await http_client.get(f"{LLAMACPP_URL}/models")
                    data2 = r2.json()
                    models2 = data2.get("data", [])
                    if models2 and models2[0].get("id") == target_model:
                        return {"success": True, "action": "loaded", "model": target_model}
                except:
                    pass
            return {"success": True, "action": "loaded_timeout", "model": target_model}
        elif r.status_code == 400:
            text = await r.aread()
            # Model might already be loaded
            if "already" in text.lower() or "running" in text.lower():
                return {"success": True, "action": "already_loaded", "model": target_model}
            return {"success": False, "error": text}
        else:
            return {"success": False, "error": f"HTTP {r.status_code}: {await r.aread()}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
        return r.json() if r.status_code == 200 else {"data": [{"id": VISION_MODEL}]}
    except Exception:
        return {"data": [{"id": VISION_MODEL, "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(body: dict):
    """Proxy chat completions to llama.cpp.
    OhMyCaptcha's reCAPTCHA v2 solver uses this for audio transcription."""
    target_model = body.get("model", VISION_MODEL)

    # Ensure vision model is loaded for audio transcription too
    load_result = await _ensure_model_loaded(target_model)
    if not load_result.get("success"):
        raise HTTPException(status_code=502, detail=f"Model load failed: {load_result.get('error')}")

    # Forward request to llama.cpp
    try:
        r = await http_client.post(
            f"{LLAMACPP_URL}/v1/chat/completions",
            json=body,
            timeout=300.0
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"llama.cpp error: {e}")
    finally:
        if UNLOAD_AFTER_SOLVE:
            await _unload_model()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
