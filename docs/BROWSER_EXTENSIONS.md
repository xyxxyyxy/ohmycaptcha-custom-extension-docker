# Browser Extensions for CAPTCHA Solving & Bot Detection Evasion

## The Problem

When OhMyCaptcha (via CDP) controls Brave, Google's bot detection triggers because:

1. **navigator.webdriver = true** - Playwright/CDP sets this flag
2. **Missing browser plugins** - Headless/controlled browsers report 0 plugins
3. **AutomationControlled flag** - Chrome disables features when this is set
4. **Consistent fingerprint** - Same canvas, WebGL, font fingerprint every time
5. **No mouse movement history** - reCAPTCHA v3 scores based on behavior

## Recommended Extensions (Install Order Matters)

### Tier 1: Essential (Install These First)

#### 1. Buster: Captcha Solver for Humans
- **What**: Solves reCAPTCHA v2 by clicking the audio challenge and using speech recognition
- **Where**: https://github.com/dessant/buster or Chrome Web Store
- **Why**: OhMyCaptcha's reCAPTCHA v2 solver falls back to audio transcription but needs an STT model. Buster does this locally for free.
- **Install**:
  ```bash
  # Download latest release
  wget https://github.com/dessant/buster/releases/latest/download/buster-chrome.zip
  unzip buster-chrome.zip -d ~/buster-extension
  # Brave -> chrome://extensions/ -> Developer mode -> Load unpacked -> select ~/buster-extension
  ```

#### 2. User-Agent Switcher and Manager
- **What**: Spoofs your browser's user agent string
- **Where**: Chrome Web Store - search "User-Agent Switcher and Manager"
- **Why**: Prevents consistent user-agent fingerprinting. Rotate between common Chrome UA strings.
- **Config**: Set to rotate daily, use only desktop Chrome UAs

#### 3. WebRTC Control
- **What**: Prevents WebRTC from leaking your real IP address
- **Where**: Chrome Web Store - search "WebRTC Control"
- **Why**: WebRTC can leak LAN IP which differs from your public IP = bot signal
- **Config**: Set to "Disable non-proxied UDP"

### Tier 2: Anti-Detection (Reduces Bot Score)

#### 4. Canvas Fingerprint Defender
- **What**: Returns random canvas fingerprint on every read
- **Where**: Chrome Web Store - search "Canvas Fingerprint Defender"
- **Why**: reCAPTCHA v3 uses canvas fingerprinting to track users

#### 5. WebGL Fingerprint Defender  
- **What**: Returns random WebGL fingerprint on every read
- **Where**: Chrome Web Store - search "WebGL Fingerprint Defender"
- **Why**: Paired with Canvas Defender for complete fingerprint randomization

#### 6. Font Fingerprint Defender
- **What**: Returns consistent but common font list
- **Where**: Chrome Web Store - search "Font Fingerprint Defender"
- **Why**: Bot detection checks installed fonts (too few = bot, too many = unique)

#### 7. Privacy Pass
- **What**: Generates blind tokens to skip Cloudflare/hCaptcha challenges
- **Where**: https://github.com/privacypass/challenge-bypass-extension
- **Why**: Reduces number of hCaptcha challenges you see dramatically

### Tier 3: Automation Helpers

#### 8. OhMyCaptcha Solver (Your Extension)
- Already installed. Set API URL to http://192.168.3.25:1231

#### 9. FlareSolverr (If Cloudflare blocks)
- Docker container already in docker-compose.yml
- Handles Cloudflare IUAM/Challenge pages

## Quick Install Script

Save as `install-extensions.sh` and run:

```bash
#!/bin/bash
# Install CAPTCHA-solving helper extensions for Brave

set -e
EXT_DIR="$HOME/brave-extensions"
mkdir -p "$EXT_DIR"

echo "=== Installing Buster CAPTCHA Solver ==="
cd "$EXT_DIR"
rm -rf buster
BUSTER_URL=$(curl -s https://api.github.com/repos/dessant/buster/releases/latest | grep "browser_download_url.*chrome.zip" | cut -d '"' -f 4)
wget -q "$BUSTER_URL" -O buster.zip
unzip -q buster.zip -d buster
rm buster.zip
echo "Buster downloaded to $EXT_DIR/buster"
echo "Install manually: chrome://extensions/ -> Developer mode -> Load unpacked -> $EXT_DIR/buster"

echo ""
echo "=== Extension Install Checklist ==="
echo "1. Open Brave -> chrome://extensions/"
echo "2. Enable Developer mode (toggle top-right)"
echo "3. Click 'Load unpacked' and select: $EXT_DIR/buster"
echo "4. Install from Chrome Web Store (search each):"
echo "   - User-Agent Switcher and Manager"
echo "   - WebRTC Control"  
echo "   - Canvas Fingerprint Defender"
echo "   - WebGL Fingerprint Defender"
echo "   - Font Fingerprint Defender"
echo "   - Privacy Pass"
echo ""
echo "5. Reload OhMyCaptcha Solver extension"
echo "6. Test at: https://www.google.com/recaptcha/api2/demo"
```

## Extension Settings for Best Results

### Buster
- Enable "Simulate user interactions" (install the client app if needed)
- Enable "Auto-submit"
- Set recognition service: "Wit Speech API" (free tier available)

### User-Agent Switcher
- Mode: Automatic rotation
- Interval: Every session
- Filter: Desktop only (Windows/Mac Chrome)
- Spoof: Navigator, Screen resolution, Date/Timezone

### Canvas/WebGL/Font Defenders
- Set to "Random" mode (not "Block" - blocking is also detectable)
- Allow on all sites

## Why hCaptcha Idles

hCaptcha is harder than reCAPTCHA because:
1. **No audio challenge** - Unlike reCAPTCHA, hCaptcha's audio is often disabled
2. **Mouse movement tracking** - hCaptcha heavily weights mouse path analysis
3. **Cookie profiling** - hCaptcha checks cross-site cookie history
4. **Rate limiting** - hCaptcha aggressively rate-limits IPs with many solves

**Solutions for hCaptcha:**
- Install **Privacy Pass** - this is the #1 hCaptcha helper (reduces challenges by ~90%)
- Enable **User-Agent rotation** - hCaptcha checks for consistent fingerprint
- Consider **hektCaptcha** extension (hCaptcha-specific AI solver, free)
- Let the browser "warm up" - browse normally for 5-10 minutes before solving

## Testing Your Setup

After installing all extensions, test progressively:

```bash
# Test 1: reCAPTCHA v2 checkbox
curl -s http://localhost:1231/api/v1/health  # Bridge must be running
# Then visit: https://www.google.com/recaptcha/api2/demo

# Test 2: hCaptcha
curl -s http://localhost:1231/api/v1/health
# Then visit: https://accounts.hcaptcha.com/demo

# Test 3: reCAPTCHA v3
# Visit any site with invisible reCAPTCHA
```

## Troubleshooting

### "Automated requests" on reCAPTCHA
- **Cause**: Bot detection fingerprint too strong
- **Fix**: Install Canvas + WebGL + Font defenders. Enable User-Agent rotation.

### hCaptcha loads but nothing happens
- **Cause**: OhMyCaptcha can't interact with hCaptcha iframe
- **Fix**: Install Privacy Pass first. Let browser warm up.

### Bridge connects but solves fail
- **Cause**: Brave window too "sterile" (no history, cookies)
- **Fix**: Use Brave's default profile (not a fresh one). Browse normally for a bit.

### Extension conflicts
- **Cause**: Multiple extensions modifying the same page
- **Fix**: Disable Buster auto-solve. Let OhMyCaptcha handle it. Use Buster as fallback.
