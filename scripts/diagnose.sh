#!/usr/bin/env bash
#
# Diagnostic script to check all services and identify issues.
# Run this after docker compose up -d to see what's working and what's not.

set -euo pipefail

echo "=========================================="
echo "  CAPTCHA STACK DIAGNOSTICS"
echo "=========================================="

# ── 1. Check all containers ──
echo ""
echo "--- Docker Containers ---"
docker compose ps 2>/dev/null || echo "docker compose not available"

# ── 2. Port checks ──
echo ""
echo "--- Port Listeners ---"
for port in 6663 1232 1231 1233 8191; do
    if nc -z localhost $port 2>/dev/null; then
        echo "  Port $port: LISTENING"
    else
        echo "  Port $port: NOT REACHABLE"
    fi
done

# ── 3. Service checks ──
echo ""
echo "--- Service Health ---"

echo -n "  Vision (6663/health): "
curl -sf http://localhost:6663/health >/dev/null 2>&1 && echo "OK" || echo "FAIL"

echo -n "  Vision (6663/models): "
curl -sf http://localhost:6663/models >/dev/null 2>&1 && echo "OK" || echo "FAIL"

echo -n "  Shim (1232/stats):    "
curl -sf http://localhost:1232/stats >/dev/null 2>&1 && echo "OK" || echo "FAIL"

echo -n "  Shim (1232/health):   "
curl -sf http://localhost:1232/health >/dev/null 2>&1 && echo "OK" || echo "FAIL"

echo -n "  Bridge (1231/health): "
curl -sf http://localhost:1231/api/v1/health >/dev/null 2>&1 && echo "OK" || echo "FAIL"

echo -n "  Whisper (1233):       "
curl -sf http://localhost:1233/v1/audio/transcriptions >/dev/null 2>&1 && echo "OK" || echo "FAIL"

echo -n "  FlareSolverr (8191):  "
curl -sf http://localhost:8191 >/dev/null 2>&1 && echo "OK" || echo "FAIL"

# ── 4. Vision server logs (last 20 lines) ──
echo ""
echo "--- Vision Server Logs (last 20) ---"
docker logs --tail 20 llamacpp-vision 2>/dev/null || echo "  Container not running"

# ── 5. Shim logs ──
echo ""
echo "--- Shim Logs (last 20) ---"
docker logs --tail 20 captcha-solver 2>/dev/null || echo "  Container not running"

# ── 6. Whisper logs ──
echo ""
echo "--- Whisper Logs (last 20) ---"
docker logs --tail 20 whisper 2>/dev/null || echo "  Container not running"

# ── 7. Test vision chat directly ──
echo ""
echo "--- Direct Vision Chat Test ---"
if command -v python3 &>/dev/null; then
    RESULT=$(python3 -c '
import base64, io, json, urllib.request
from PIL import Image
img = Image.new("RGB", (30, 30), "blue")
buf = io.BytesIO()
img.save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
payload = json.dumps({
    "model": "Qwen3VL-8B-Instruct-Q4_K_M",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Color?"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
    ]}],
    "max_tokens": 10
}).encode()
try:
    req = urllib.request.Request("http://localhost:6663/v1/chat/completions",
        data=payload, headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    print(f"  OK: {data[\"choices\"][0][\"message\"][\"content\"]}")
except Exception as e:
    print(f"  FAIL: {e}")
')
    echo "$RESULT"
else
    echo "  python3 not available, skipping"
fi

echo ""
echo "=========================================="
echo "  SUMMARY"
echo "=========================================="
echo "If Vision shows OK but Shim shows FAIL:"
echo "  docker compose up -d captcha-solver"
echo ""
echo "If Whisper shows FAIL:"
echo "  docker logs whisper"
echo ""
echo "If anything else FAILs:"
echo "  Check logs above for error messages"
echo "=========================================="
