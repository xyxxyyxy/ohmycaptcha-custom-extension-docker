# Self-Hosted CAPTCHA Solver Stack (Desktop + Brave)

## Architecture (2 machines)

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
```

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
cd ~/Downloads/captcha_stack
./start-brave.sh
```

**Auto-start on boot (systemd):**
```bash
cd ~/Downloads/captcha_stack/systemd
sudo ./install-services.sh leonardomoya
```

This creates:
- `brave-cdp@leonardomoya.service` — starts Brave with CDP on graphical session start
- `captcha-bridge@leonardomoya.service` — starts Docker bridge after Brave

Verify CDP:
```bash
curl http://localhost:9222/json/version
```

### 3. Start Docker stack

```bash
cd ~/Downloads/captcha_stack
docker compose up -d --build
```

Verify:
```bash
curl http://localhost:1232/health        # shim
curl http://localhost:1231/api/v1/health   # bridge + CDP status
```

### 4. Install extension

1. Chrome → `chrome://extensions/` → Developer mode ON
2. Load unpacked → select `ohmycaptcha-solver-ext/`
3. Set API URL to `http://localhost:1231`
4. Set API Key to `local`

## Troubleshooting

**"Missing X server or $DISPLAY"**
- Brave needs a graphical session. The `start-brave.sh` script auto-detects DISPLAY.
- If running over SSH, use: `ssh -X user@host` then run `./start-brave.sh`
- For systemd auto-start, use `graphical-session.target` (already configured)

**Extension button not appearing:**
- Check `chrome://extensions/` → Errors
- Open DevTools on CAPTCHA page → Console
- Check `typeof window.registerCaptchaWidget` — should be "function"
- Check `typeof window.$` — should be "function" (jQuery stub loaded)
- Check Network tab for `jquery.min.js` — should load without CSP errors

**"$ is not defined" in hunter.js:**
- The jQuery stub is now bundled inline (no CDN). It defines `window.$` before hunters run.
- If still missing, check console for earlier errors in `jquery.min.js`

**Bridge can't connect to Brave CDP:**
- Ensure Brave is running: `curl http://localhost:9222/json/version`
- Check `sudo systemctl status brave-cdp@leonardomoya`
- The bridge has `restart: unless-stopped` and will retry
