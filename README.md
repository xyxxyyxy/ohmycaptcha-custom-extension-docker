# Self-Hosted CAPTCHA Solver Stack (Desktop + Brave)

Uses **[OhMyCaptcha](https://github.com/shenhao-stu/ohmycaptcha)** with CDP patches to connect to a real Brave browser instead of launching its own headless Chromium.

## Architecture

```
DESKTOP (Docker host + Brave browser)
  ┌─────────────────┐     ┌─────────────────────────────────────────┐
  │  Brave Browser  │     │  Docker Stack                           │
  │  --remote-debugging-port=9222      │  captcha-bridge (OhMyCaptcha)         │
  │  (default profile)                 │    port 1231                            │
  │                                    │  YesCaptcha API + CDP patches           │
  └─────────────────┘     └─────────────────────────────────────────┘
          │                           │
          │ CDP                       │ HTTP
          │                           ▼
          │                 ┌─────────────────┐     ┌─────────────────┐
          │                 │  captcha-solver │────▶│  WORKSTATION    │
          │                 │  port 1232      │     │  llama.cpp      │
          │                 │  model swapper  │     │  Qwen3VL        │
          │                 └─────────────────┘     │  (via nginx)    │
          │                                         └─────────────────┘
          │
          │  Image grid flow:
          │    OhMyCaptcha → CDP Brave → screenshot → POST to Shim → Qwen3VL
          │    → click tiles → verify → token
          │
          │  Token flow:
          │    OhMyCaptcha → CDP Brave → click/wait → token
          │
          │  Audio challenge flow:
          │    OhMyCaptcha → CDP Brave → switch to audio → download → STT → token
```

### Supported CAPTCHA Types

OhMyCaptcha supports the full YesCaptcha protocol:

| Type | Endpoint | Method |
|------|----------|--------|
| reCAPTCHA V2 (checkbox) | `RecaptchaV2TaskProxyless` | CDP click + token extract |
| reCAPTCHA V2 (invisible) | `RecaptchaV2TaskProxyless` | CDP click + token extract |
| reCAPTCHA V2 Enterprise | `RecaptchaV2EnterpriseTaskProxyless` | CDP click + token extract |
| reCAPTCHA V2 image grid | `ReCaptchaV2Classification` | CDP screenshot + vision |
| reCAPTCHA V3 | `RecaptchaV3TaskProxyless` | CDP `grecaptcha.execute()` |
| reCAPTCHA V3 Enterprise | `RecaptchaV3EnterpriseTask` | CDP `grecaptcha.execute()` |
| hCaptcha | `HCaptchaTaskProxyless` | CDP click + token extract |
| hCaptcha image | `HCaptchaClassification` | CDP screenshot + vision |
| Cloudflare Turnstile | `TurnstileTaskProxyless` | CDP click + token extract |
| Image-to-text | `ImageToTextTask` | Vision model direct |

## Setup

### 1. Install Brave

```bash
sudo apt install curl
sudo curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main"|sudo tee /etc/apt/sources.list.d/brave-browser-release.list
sudo apt update
sudo apt install brave-browser
```

### 2. Start Brave with remote debugging

**Manual:**
```bash
cd ~/captcha_stack
./start-brave.sh
```

**Auto-start on boot (systemd):**
```bash
cd ~/captcha_stack/systemd
sudo ./install-services.sh $USER
```

Verify CDP:
```bash
curl http://localhost:9222/json/version
```

### 3. Start Docker stack

```bash
cd ~/captcha_stack
docker compose up -d --build
```

Verify:
```bash
curl http://localhost:1232/health        # shim
curl http://localhost:1231/api/v1/health   # OhMyCaptcha bridge + CDP status
```

### 4. Install extension

1. Chrome → `chrome://extensions/` → Developer mode ON
2. Load unpacked → select `ohmycaptcha-solver-ext/`
3. Set API URL to `http://localhost:1231`
4. Set API Key to `local`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CDP_URL` | `http://host.docker.internal:9222` | Chrome DevTools Protocol endpoint |
| `CLIENT_KEY` | `local` | API key for extension authentication |
| `CAPTCHA_RETRIES` | `3` | Max retries per solve attempt |
| `CAPTCHA_TIMEOUT` | `60` | Seconds before giving up on a solve |
| `BROWSER_TIMEOUT` | `30` | Seconds for page navigation |
| `CLOUD_BASE_URL` | — | OpenAI-compatible endpoint (cloud model) |
| `CLOUD_API_KEY` | — | API key for cloud model |
| `LOCAL_BASE_URL` | `http://captcha-solver:8000/v1` | Local llama.cpp endpoint |
| `LOCAL_MODEL` | `Qwen3VL-8B-Instruct-Q4_K_M` | Vision model name |

## Troubleshooting

**"Missing X server or $DISPLAY"**
- Brave needs a graphical session. The `start-brave.sh` script auto-detects DISPLAY.
- If running over SSH, use: `ssh -X user@host` then run `./start-brave.sh`

**Extension button not appearing:**
- Check `chrome://extensions/` → Errors
- Open DevTools on CAPTCHA page → Console
- Check `typeof window.registerCaptchaWidget` — should be "function"
- Check `typeof window.$` — should be "function" (jQuery stub loaded)
- The interceptors handle CAPTCHA libraries that load before the content script, but some sites use custom loaders. Check the hunter scripts for your CAPTCHA type.

**"$ is not defined" in hunter.js:**
- The jQuery stub is bundled inline (no CDN). It defines `window.$` before hunters run.
- If still missing, check console for earlier errors in `jquery.min.js`

**Bridge can't connect to Brave CDP:**
- Ensure Brave is running: `curl http://localhost:9222/json/version`
- Check `sudo systemctl status brave-cdp@$USER`
- The bridge has `restart: unless-stopped` and will retry

## Standalone Bridge (Alternative)

A lightweight custom bridge (`captcha-bridge/main_standalone.py`) is included as a fallback. It supports a smaller subset of CAPTCHA types but has no external dependencies beyond the Docker image. To use it instead of OhMyCaptcha:

```dockerfile
# In captcha-bridge/Dockerfile, replace the CMD line:
CMD ["python", "-m", "uvicorn", "main_standalone:app", "--host", "0.0.0.0", "--port", "8000"]
```

## What's Different from Pure OhMyCaptcha

| | Pure OhMyCaptcha | This Stack |
|---|---|---|
| Browser | Headless Chromium in container | Real Brave via CDP |
| Bot detection | High (headless) | Low (real profile + cookies) |
| Display | Xvfb virtual | Real monitor |
| Image tasks | Direct vision API | Through captcha-solver shim |
| Model | Single backend | Dual: cloud + local swapper |
