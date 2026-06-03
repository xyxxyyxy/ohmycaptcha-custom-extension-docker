#!/bin/bash
# Run this ON THE DESKTOP before starting containers

BRAVE_PROFILE="${HOME}/.config/BraveSoftware/Brave-Browser"

# Detect display - try multiple methods
if [ -z "$DISPLAY" ]; then
    # Method 1: check w command for active display
    ACTIVE_DISPLAY=$(w -sh | grep -oP ':\d+' | head -1)
    if [ -n "$ACTIVE_DISPLAY" ]; then
        export DISPLAY="$ACTIVE_DISPLAY"
    fi
fi

if [ -z "$DISPLAY" ]; then
    # Method 2: check /tmp/.X11-unix sockets
    for d in $(ls /tmp/.X11-unix/ 2>/dev/null | sed 's/X/:/'); do
        if xset -q -display $d >/dev/null 2>&1; then
            export DISPLAY="$d"
            break
        fi
    done
fi

if [ -z "$DISPLAY" ]; then
    # Method 3: fallback common displays
    for d in :1 :0 :2; do
        if xset -q -display $d >/dev/null 2>&1; then
            export DISPLAY=$d
            break
        fi
    done
fi

if [ -z "$DISPLAY" ]; then
    echo "ERROR: No DISPLAY found."
    echo "If running over SSH, use: ssh -X user@host"
    echo "If on a desktop session, check: echo $DISPLAY"
    exit 1
fi

echo "Using DISPLAY=$DISPLAY"

# Detect XAUTHORITY
if [ -z "$XAUTHORITY" ]; then
    for xauth in /run/user/$(id - u)/gdm/Xauthority /run/user/$(id - u)/.mutter-Xwaylandauth.* /home/*/.Xauthority /tmp/.Xauth*; do
        if [ -f "$xauth" ]; then
            export XAUTHORITY="$xauth"
            echo "Using XAUTHORITY=$XAUTHORITY"
            break
        fi
    done
fi

# Kill existing Brave with remote debugging
pkill -f "remote-debugging-port=9222" 2>/dev/null
sleep 1

echo "Starting Brave with remote debugging on port 9222..."
echo "Profile: $BRAVE_PROFILE"
echo ""

# Find Brave binary
for bin in brave-browser brave /usr/bin/brave-browser /usr/bin/brave /opt/brave.com/brave/brave; do
    if command -v "$bin" &>/dev/null || [ -x "$bin" ]; then
        BRAVE_BIN="$(command -v "$bin" 2>/dev/null || echo "$bin")"
        break
    fi
done

if [ -z "$BRAVE_BIN" ]; then
    echo "ERROR: Brave not found. Install: sudo apt install brave-browser"
    exit 1
fi

echo "Using: $BRAVE_BIN"

# Start Brave
"$BRAVE_BIN" \
    --user-data-dir="$BRAVE_PROFILE" \
    --remote-debugging-port=9222 \
    --remote-debugging-address=0.0.0.0 \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --window-size=1280,900 \
    --start-maximized \
    about:blank &

BRAVE_PID=$!
echo "Brave PID: $BRAVE_PID"
echo ""
echo "Test CDP from host:  curl http://localhost:9222/json/version"
echo "Test CDP from Docker: curl http://host.docker.internal:9222/json/version"
echo "If Docker test fails, ensure --remote-debugging-address=0.0.0.0 is set"
echo ""

wait $BRAVE_PID
