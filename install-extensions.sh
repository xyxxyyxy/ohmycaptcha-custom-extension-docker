#!/bin/bash
# Install CAPTCHA-solving helper extensions for Brave
# Run this on the desktop computer where Brave is running

set -e

EXT_DIR="$HOME/brave-extensions"
mkdir -p "$EXT_DIR"

echo "=========================================="
echo "  CAPTCHA Helper Extensions Installer"
echo "=========================================="
echo ""

# Check Brave is installed
if ! command -v brave-browser &> /dev/null; then
    echo "ERROR: brave-browser not found in PATH"
    echo "Install Brave first: https://brave.com/linux"
    exit 1
fi

echo "=== Step 1/5: Downloading Buster CAPTCHA Solver ==="
cd "$EXT_DIR"
rm -rf buster buster.zip

# Get latest Buster release URL
BUSTER_URL=$(curl -sL https://api.github.com/repos/dessant/buster/releases/latest | grep "browser_download_url.*chrome.zip" | cut -d '"' -f 4)

if [ -z "$BUSTER_URL" ]; then
    echo "WARNING: Could not get Buster download URL. Using fallback..."
    BUSTER_URL="https://github.com/dessant/buster/releases/download/v3.1.0/buster-chrome-v3.1.0.zip"
fi

echo "Downloading from: $BUSTER_URL"
wget -q --show-progress "$BUSTER_URL" -O buster.zip
unzip -q -o buster.zip -d buster
rm buster.zip
echo "Buster installed to: $EXT_DIR/buster"
echo ""

echo "=== Step 2/5: Downloading Privacy Pass ==="
cd "$EXT_DIR"
rm -rf privacypass

# Privacy Pass extension
PP_URL=$(curl -sL https://api.github.com/privacypass/challenge-bypass-extension/releases/latest | grep "browser_download_url.*chrome" | cut -d '"' -f 4)
if [ -n "$PP_URL" ]; then
    wget -q --show-progress "$PP_URL" -O privacypass.zip
    unzip -q -o privacypass.zip -d privacypass
    rm privacypass.zip
    echo "Privacy Pass installed to: $EXT_DIR/privacypass"
else
    echo "Privacy Pass: Install manually from Chrome Web Store"
    echo "  Search: 'Privacy Pass'"
fi
echo ""

echo "=== Step 3/5: Creating extension loader helper ==="
cat > "$EXT_DIR/load-extensions.sh" << 'EOF'
#!/bin/bash
# Helper to launch Brave with extensions pre-loaded

EXT_DIR="$HOME/brave-extensions"

# Build extension list
EXTENSIONS=""
[ -d "$EXT_DIR/buster" ] && EXTENSIONS="${EXTENSIONS},${EXT_DIR/buster}"
[ -d "$EXT_DIR/privacypass" ] && EXTENSIONS="${EXTENSIONS},${EXT_DIR/privacypass}"

# Remove leading comma
EXTENSIONS="${EXTENSIONS#,}"

if [ -z "$EXTENSIONS" ]; then
    echo "No extensions found in $EXT_DIR"
    exit 1
fi

echo "Launching Brave with extensions:"
echo "  - Buster CAPTCHA Solver"
[ -d "$EXT_DIR/privacypass" ] && echo "  - Privacy Pass"
echo ""

# Launch Brave with extensions
brave-browser \
    --load-extension="$EXTENSIONS" \
    --user-data-dir="$HOME/.config/BraveSoftware/Brave-Browser" \
    --remote-debugging-port=9222 \
    --remote-debugging-address=0.0.0.0 \
    --no-first-run \
    --no-default-browser-check \
    about:blank
EOF
chmod +x "$EXT_DIR/load-extensions.sh"
echo "Created: $EXT_DIR/load-extensions.sh"
echo ""

echo "=== Step 4/5: Manual Extension Installation ==="
echo ""
echo "The following extensions must be installed from the Chrome Web Store:"
echo ""
echo "  1. User-Agent Switcher and Manager"
echo "     - Search in Chrome Web Store"
echo "     - Set to rotate daily, desktop Chrome only"
echo ""
echo "  2. WebRTC Control"
echo "     - Search in Chrome Web Store"
echo "     - Set to 'Disable non-proxied UDP'"
echo ""
echo "  3. Canvas Fingerprint Defender"
echo "     - Search in Chrome Web Store"
echo "     - Set to 'Random' mode"
echo ""
echo "  4. WebGL Fingerprint Defender"
echo "     - Search in Chrome Web Store"
echo "     - Set to 'Random' mode"
echo ""
echo "  5. Font Fingerprint Defender (optional)"
echo "     - Search in Chrome Web Store"
echo ""

echo "=== Step 5/5: Install Buster + Privacy Pass in Brave ==="
echo ""
echo "1. Open Brave: brave-browser"
echo "2. Go to: chrome://extensions/"
echo "3. Enable Developer mode (toggle top-right)"
echo "4. Click 'Load unpacked'"
echo "5. Select: $EXT_DIR/buster"
[ -d "$EXT_DIR/privacypass" ] && echo "6. Click 'Load unpacked' again" && echo "7. Select: $EXT_DIR/privacypass"
echo ""

echo "=== OR use the helper script ==="
echo "   $EXT_DIR/load-extensions.sh"
echo "   (This launches Brave with Buster + Privacy Pass pre-loaded)"
echo ""

echo "=== After extensions are loaded ==="
echo "1. Reload OhMyCaptcha Solver extension"
echo "2. Set API URL: http://192.168.3.25:1231"
echo "3. Test at: https://www.google.com/recaptcha/api2/demo"
echo ""
echo "=== Extension config tips ==="
echo "- Buster: Enable auto-submit, install client app for better success"
echo "- UA Switcher: Rotate daily, Windows Chrome desktop only"
echo "- Canvas/WebGL defenders: Random mode (NOT block mode)"
echo "- Privacy Pass: Click the extension icon to get tokens before solving"
echo ""
echo "Done! Extensions installed to: $EXT_DIR"
